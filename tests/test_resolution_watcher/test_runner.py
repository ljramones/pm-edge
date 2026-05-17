from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from data.resolution_watcher.runner import (
    ResolutionWatcherRunner,
    detect_disappeared_candidates,
    detect_resolution_candidates,
    find_final_book_snapshot,
    load_seen_resolutions,
)
from data.resolution_watcher.schema import (
    FinalBookSnapshot,
    MarketResolutionCandidate,
    ResolvedMarketOutcome,
)
from data.resolution_watcher.settings import ResolutionWatcherSettings

from .conftest import (
    metadata_row,
    metadata_schema,
    old_metadata_row,
    old_metadata_schema,
    snapshot_row,
    snapshot_schema,
    write_table,
)


class FakeClient:
    venue = "polymarket"

    def __init__(self) -> None:
        self.fetch_count = 0

    async def fetch_resolution_outcome(
        self,
        candidate: MarketResolutionCandidate,
        *,
        detected_at: datetime,
        final_snapshot: FinalBookSnapshot,
    ) -> ResolvedMarketOutcome | None:
        self.fetch_count += 1
        return ResolvedMarketOutcome(
            venue=candidate.venue,
            market_id=candidate.market_id,
            resolution_timestamp_utc=detected_at,
            venue_resolved_at_utc=None,
            resolved_value=1.0,
            resolution_source="metadata_status",
            final_top_bid=final_snapshot.top_bid,
            final_top_ask=final_snapshot.top_ask,
            final_spread=final_snapshot.spread,
            final_snapshot_timestamp_utc=final_snapshot.timestamp_utc,
            metadata_snapshot_id=candidate.metadata_snapshot_id,
        )

    async def close(self) -> None:
        return None


class FailingClient(FakeClient):
    async def fetch_resolution_outcome(
        self,
        candidate: MarketResolutionCandidate,
        *,
        detected_at: datetime,
        final_snapshot: FinalBookSnapshot,
    ) -> ResolvedMarketOutcome | None:
        raise RuntimeError("venue failed")


class ApiResolvedClient(FakeClient):
    def __init__(self, *, venue: str = "polymarket", resolved: bool = True) -> None:
        super().__init__()
        self.venue = venue
        self.resolved = resolved

    async def fetch_resolution_outcome(
        self,
        candidate: MarketResolutionCandidate,
        *,
        detected_at: datetime,
        final_snapshot: FinalBookSnapshot,
    ) -> ResolvedMarketOutcome | None:
        self.fetch_count += 1
        if not self.resolved:
            return None
        return ResolvedMarketOutcome(
            venue=candidate.venue,
            market_id=candidate.market_id,
            resolution_timestamp_utc=detected_at,
            venue_resolved_at_utc=None,
            resolved_value=1.0,
            resolution_source=f"{candidate.venue}_api",
            final_top_bid=final_snapshot.top_bid,
            final_top_ask=final_snapshot.top_ask,
            final_spread=final_snapshot.spread,
            final_snapshot_timestamp_utc=final_snapshot.timestamp_utc,
            metadata_snapshot_id=candidate.metadata_snapshot_id,
        )


class StopAfterOneCycleRunner(ResolutionWatcherRunner):
    async def run_once(self) -> None:
        await super().run_once()
        await self.stop()


@pytest.mark.asyncio
async def test_runner_run_once_processes_detected_resolution(
    source_archive: Path,
    tmp_path: Path,
) -> None:
    settings = ResolutionWatcherSettings(
        source_dir=source_archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    client = FakeClient()
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()

    assert runner.total_resolved_since_start == 1
    assert ("polymarket", "poly-1") in runner.seen_resolutions
    assert client.fetch_count == 0
    assert list((tmp_path / "resolved").glob("venue=polymarket/date=*/*.parquet"))
    rows = [
        row
        for path in (tmp_path / "resolved").glob("venue=polymarket/date=*/*.parquet")
        for row in pq.ParquetFile(path).read().to_pylist()
    ]
    assert rows[0]["resolved_value"] == 1.0
    assert rows[0]["resolution_source"] == "metadata_status"
    assert rows[0]["final_top_bid"] == 0.40


@pytest.mark.asyncio
async def test_runner_uses_api_fallback_for_closed_unresolved_market(
    tmp_path: Path,
    base_time: datetime,
) -> None:
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        [
            metadata_row(
                "polymarket",
                "poly-ambiguous",
                base_time,
                base_time - timedelta(hours=1),
                "closed",
                {"conditionId": "poly-ambiguous"},
                is_resolved=False,
                is_closed=True,
                resolution_outcome=None,
            )
        ],
        metadata_schema(),
    )
    write_table(
        archive / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-16" / "part.parquet",
        [snapshot_row("polymarket", "poly-ambiguous", base_time - timedelta(minutes=5))],
        snapshot_schema(),
    )
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    client = FakeClient()
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()

    assert runner.total_resolved_since_start == 1
    assert client.fetch_count == 1
    assert runner.api_fallbacks_since_heartbeat == 1


@pytest.mark.asyncio
async def test_runner_uses_detection_time_for_final_book_when_resolution_time_missing(
    tmp_path: Path,
    base_time: datetime,
) -> None:
    archive = tmp_path / "forward_index"
    row = metadata_row(
        "polymarket",
        "poly-no-venue-time",
        base_time,
        base_time - timedelta(hours=1),
        "closed",
        {"conditionId": "poly-no-venue-time"},
        is_resolved=True,
        is_closed=True,
        resolution_outcome="YES",
    )
    row["resolution_timestamp_utc"] = None
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        [row],
        metadata_schema(),
    )
    earlier_snapshot = snapshot_row(
        "polymarket",
        "poly-no-venue-time",
        base_time - timedelta(minutes=10),
    )
    latest_snapshot = snapshot_row(
        "polymarket",
        "poly-no-venue-time",
        base_time + timedelta(minutes=5),
    )
    latest_snapshot["top_bid"] = 0.88
    latest_snapshot["top_ask"] = 0.92
    latest_snapshot["spread"] = 0.04
    write_table(
        archive / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-16" / "part.parquet",
        [earlier_snapshot, latest_snapshot],
        snapshot_schema(),
    )
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": FakeClient()})

    await runner.run_once()

    rows = [
        row
        for path in (tmp_path / "resolved").glob("venue=polymarket/date=*/*.parquet")
        for row in pq.ParquetFile(path).read().to_pylist()
    ]
    assert len(rows) == 1
    assert rows[0]["final_top_bid"] == 0.88
    assert rows[0]["final_top_ask"] == 0.92
    assert rows[0]["final_spread"] == 0.04
    assert rows[0]["final_snapshot_timestamp_utc"] == latest_snapshot["timestamp_utc"]


@pytest.mark.asyncio
async def test_runner_deduplicates_seen_resolutions(
    source_archive: Path,
    tmp_path: Path,
) -> None:
    settings = ResolutionWatcherSettings(
        source_dir=source_archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": FakeClient()})

    await runner.run_once()
    await runner.run_once()

    assert runner.total_resolved_since_start == 1


@pytest.mark.asyncio
async def test_runner_does_not_crash_on_per_venue_error(
    tmp_path: Path,
    base_time: datetime,
) -> None:
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        [
            metadata_row(
                "polymarket",
                "poly-ambiguous",
                base_time,
                base_time - timedelta(hours=1),
                "closed",
                {"conditionId": "poly-ambiguous"},
                resolution_outcome=None,
            )
        ],
        metadata_schema(),
    )
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": FailingClient()})

    await runner.run_once()

    assert runner.total_resolved_since_start == 0


def test_detect_resolution_candidates_reads_latest_metadata(
    source_archive: Path,
    base_time: datetime,
) -> None:
    detection = detect_resolution_candidates(
        source_archive,
        venue="polymarket",
        seen=set(),
        now=base_time + datetime.resolution,
    )

    assert detection.metadata_candidates_seen == 1
    assert [candidate.market_id for candidate in detection.candidates] == ["poly-1"]
    assert detection.candidates[0].resolution_outcome == "YES"


def test_detect_resolution_candidates_old_schema_returns_empty(
    tmp_path: Path,
    base_time: datetime,
) -> None:
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        [
            old_metadata_row(
                "polymarket",
                "poly-old",
                base_time,
                base_time - timedelta(hours=1),
                "closed",
                {"closed": True, "conditionId": "poly-old"},
            )
        ],
        old_metadata_schema(),
    )

    detection = detect_resolution_candidates(
        archive,
        venue="polymarket",
        seen=set(),
        now=base_time + datetime.resolution,
    )

    assert detection.metadata_candidates_seen == 0
    assert detection.candidates == []


def test_detect_resolution_candidates_limits_to_recent_metadata(
    tmp_path: Path,
    base_time: datetime,
) -> None:
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-01"
        / "part.parquet",
        [
            metadata_row(
                "polymarket",
                "poly-stale",
                base_time - timedelta(days=10),
                base_time - timedelta(days=11),
                "closed",
                {"conditionId": "poly-stale"},
            )
        ],
        metadata_schema(),
    )

    detection = detect_resolution_candidates(
        archive,
        venue="polymarket",
        seen=set(),
        now=base_time,
        lookback_days=7,
    )

    assert detection.metadata_candidates_seen == 0
    assert detection.candidates == []


def test_detect_disappeared_candidates_excludes_current_and_seen_markets(
    tmp_path: Path,
    base_time: datetime,
) -> None:
    archive = tmp_path / "forward_index"
    rows = [
        metadata_row(
            "polymarket",
            f"poly-{index}",
            base_time - timedelta(hours=2),
            base_time + timedelta(hours=1),
            "active",
            {"conditionId": f"poly-{index}"},
            is_resolved=False,
            is_closed=False,
            resolution_outcome=None,
        )
        for index in range(5)
    ]
    rows.extend(
        metadata_row(
            "polymarket",
            f"poly-{index}",
            base_time - timedelta(minutes=5),
            base_time + timedelta(hours=1),
            "active",
            {"conditionId": f"poly-{index}"},
            is_resolved=False,
            is_closed=False,
            resolution_outcome=None,
        )
        for index in range(3)
    )
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        rows,
        metadata_schema(),
    )

    detection = detect_disappeared_candidates(
        archive,
        venue="polymarket",
        seen={("polymarket", "poly-3")},
        now=base_time,
    )

    assert detection.disappeared_candidates_seen == 1
    assert [candidate.market_id for candidate in detection.candidates] == ["poly-4"]


@pytest.mark.asyncio
async def test_runner_writes_disappeared_resolution_from_api(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / f"date={now.date().isoformat()}"
        / "part.parquet",
        [
            metadata_row(
                "polymarket",
                "poly-disappeared",
                now - timedelta(hours=1),
                now + timedelta(hours=1),
                "active",
                {"conditionId": "poly-disappeared"},
                is_resolved=False,
                is_closed=False,
                resolution_outcome=None,
            )
        ],
        metadata_schema(),
    )
    write_table(
        archive
        / "order_book_snapshots"
        / "venue=polymarket"
        / f"date={now.date().isoformat()}"
        / "part.parquet",
        [snapshot_row("polymarket", "poly-disappeared", now - timedelta(minutes=10))],
        snapshot_schema(),
    )
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    client = ApiResolvedClient()
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()

    rows = [
        row
        for path in (tmp_path / "resolved").glob("venue=polymarket/date=*/*.parquet")
        for row in pq.ParquetFile(path).read().to_pylist()
    ]
    assert client.fetch_count == 1
    assert len(rows) == 1
    assert rows[0]["market_id"] == "poly-disappeared"
    assert rows[0]["resolution_source"] == "polymarket_api"
    assert rows[0]["is_disappeared_detection"] is True
    assert runner.disappeared_candidates_since_heartbeat == 1
    assert runner.disappeared_resolutions_since_heartbeat == 1


@pytest.mark.asyncio
async def test_runner_skips_disappeared_market_when_api_reports_unresolved(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / f"date={now.date().isoformat()}"
        / "part.parquet",
        [
            metadata_row(
                "polymarket",
                "poly-gap",
                now - timedelta(hours=1),
                now + timedelta(hours=1),
                "active",
                {"conditionId": "poly-gap"},
                is_resolved=False,
                is_closed=False,
                resolution_outcome=None,
            )
        ],
        metadata_schema(),
    )
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    client = ApiResolvedClient(resolved=False)
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()

    assert client.fetch_count == 1
    assert runner.total_resolved_since_start == 0
    assert not list((tmp_path / "resolved").glob("venue=polymarket/date=*/*.parquet"))


@pytest.mark.asyncio
async def test_runner_limits_disappeared_api_checks(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / f"date={now.date().isoformat()}"
        / "part.parquet",
        [
            metadata_row(
                "polymarket",
                f"poly-disappeared-{index}",
                now - timedelta(hours=1, seconds=index),
                now + timedelta(hours=1),
                "active",
                {"conditionId": f"poly-disappeared-{index}"},
                is_resolved=False,
                is_closed=False,
                resolution_outcome=None,
            )
            for index in range(50)
        ],
        metadata_schema(),
    )
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
        disappeared_max_checks_per_cycle=20,
    )
    client = ApiResolvedClient(resolved=False)
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()

    assert runner.disappeared_candidates_since_heartbeat == 50
    assert client.fetch_count == 20


@pytest.mark.asyncio
async def test_runner_deduplicates_disappeared_resolution_next_cycle(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / f"date={now.date().isoformat()}"
        / "part.parquet",
        [
            metadata_row(
                "polymarket",
                "poly-once",
                now - timedelta(hours=1),
                now + timedelta(hours=1),
                "active",
                {"conditionId": "poly-once"},
                is_resolved=False,
                is_closed=False,
                resolution_outcome=None,
            )
        ],
        metadata_schema(),
    )
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    client = ApiResolvedClient()
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()
    await runner.run_once()

    assert client.fetch_count == 1
    assert runner.total_resolved_since_start == 1


@pytest.mark.asyncio
async def test_runner_loads_seen_resolutions_on_startup(
    source_archive: Path,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "resolved"
    settings = ResolutionWatcherSettings(
        source_dir=source_archive,
        output_dir=output_dir,
        venues_enabled=["polymarket"],
        poll_cadence_seconds=60,
    )
    first = ResolutionWatcherRunner(settings=settings, clients={"polymarket": FakeClient()})
    await first.run_once()
    assert first.total_resolved_since_start == 1

    second = StopAfterOneCycleRunner(settings=settings, clients={"polymarket": FakeClient()})
    await second.run()

    assert ("polymarket", "poly-1") in second.seen_resolutions
    assert second.total_resolved_since_start == 0


def test_load_seen_resolutions_handles_missing_output_dir(tmp_path: Path) -> None:
    assert load_seen_resolutions(tmp_path / "missing") == set()


@pytest.mark.asyncio
async def test_load_seen_resolutions_reads_existing_parquet(
    source_archive: Path,
    tmp_path: Path,
) -> None:
    settings = ResolutionWatcherSettings(
        source_dir=source_archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": FakeClient()})

    await runner.run_once()

    assert load_seen_resolutions(tmp_path / "resolved") == {("polymarket", "poly-1")}


def test_find_final_book_snapshot(source_archive: Path, base_time: datetime) -> None:
    snapshot = find_final_book_snapshot(
        source_archive,
        venue="polymarket",
        market_id="poly-1",
        before=base_time,
    )

    assert snapshot.top_bid == 0.40
    assert snapshot.top_ask == 0.60
    assert snapshot.spread == 0.20
