from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from data.resolution_watcher.runner import (
    FinalBookSnapshotLookup,
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
        self.close_count = 0

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
        self.close_count += 1


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


class ControlledApiClient(FakeClient):
    def __init__(
        self,
        *,
        fail_market_ids: set[str] | None = None,
        sleep_seconds: float = 0.0,
    ) -> None:
        super().__init__()
        self.fail_market_ids = fail_market_ids or set()
        self.sleep_seconds = sleep_seconds
        self.in_flight = 0
        self.max_in_flight = 0

    async def fetch_resolution_outcome(
        self,
        candidate: MarketResolutionCandidate,
        *,
        detected_at: datetime,
        final_snapshot: FinalBookSnapshot,
    ) -> ResolvedMarketOutcome | None:
        self.fetch_count += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.sleep_seconds:
                await asyncio.sleep(self.sleep_seconds)
            if candidate.market_id in self.fail_market_ids:
                raise RuntimeError(f"failed {candidate.market_id}")
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
        finally:
            self.in_flight -= 1


class StopAfterOneCycleRunner(ResolutionWatcherRunner):
    async def run_once(self) -> None:
        await super().run_once()
        await self.stop()


class StopImmediatelyRunner(ResolutionWatcherRunner):
    async def run_once(self) -> None:
        await self.stop()


class RaisingRunner(ResolutionWatcherRunner):
    async def run_once(self) -> None:
        raise RuntimeError("cycle failed")


def write_disappeared_polymarket_rows(
    archive: Path,
    *,
    now: datetime,
    count: int,
) -> None:
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
            for index in range(count)
        ],
        metadata_schema(),
    )


def resolved_market_ids(output_dir: Path) -> list[str]:
    return sorted(
        row["market_id"]
        for path in output_dir.glob("venue=polymarket/date=*/*.parquet")
        for row in pq.ParquetFile(path).read().to_pylist()
    )


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
async def test_stop_signals_without_closing_clients(
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

    await runner.stop()

    assert runner._stop.is_set()
    assert client.close_count == 0


@pytest.mark.asyncio
async def test_run_closes_clients_after_stop_exits_loop(
    source_archive: Path,
    tmp_path: Path,
) -> None:
    settings = ResolutionWatcherSettings(
        source_dir=source_archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
        poll_cadence_seconds=60,
    )
    client = FakeClient()
    runner = StopImmediatelyRunner(settings=settings, clients={"polymarket": client})

    await runner.run()

    assert client.close_count == 1


@pytest.mark.asyncio
async def test_run_closes_clients_when_cycle_raises(
    source_archive: Path,
    tmp_path: Path,
) -> None:
    settings = ResolutionWatcherSettings(
        source_dir=source_archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    client = FakeClient()
    runner = RaisingRunner(settings=settings, clients={"polymarket": client})

    with pytest.raises(RuntimeError, match="cycle failed"):
        await runner.run()

    assert client.close_count == 1


@pytest.mark.asyncio
async def test_signal_handler_stop_pattern_signals_without_closing_clients(
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

    task = asyncio.create_task(runner.stop())
    await task

    assert runner._stop.is_set()
    assert client.close_count == 0


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
    assert detection.disappeared_skipped_as_still_active == 0
    assert [candidate.market_id for candidate in detection.candidates] == ["poly-4"]


@pytest.mark.parametrize(
    ("market_id", "is_closed", "accepting_orders", "end_delta"),
    [
        ("poly-closed", True, True, timedelta(days=30)),
        ("poly-not-accepting", False, False, timedelta(days=30)),
        ("poly-expiring", False, True, timedelta(hours=23)),
    ],
)
def test_detect_disappeared_polymarket_candidates_keeps_terminal_signals(
    tmp_path: Path,
    base_time: datetime,
    market_id: str,
    is_closed: bool,
    accepting_orders: bool,
    end_delta: timedelta,
) -> None:
    archive = tmp_path / "forward_index"
    row = metadata_row(
        "polymarket",
        market_id,
        base_time - timedelta(hours=2),
        base_time + end_delta,
        "active",
        {"conditionId": market_id},
        is_resolved=False,
        is_closed=is_closed,
        resolution_outcome=None,
    )
    row["accepting_orders"] = accepting_orders
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        [row],
        metadata_schema(),
    )

    detection = detect_disappeared_candidates(
        archive,
        venue="polymarket",
        seen=set(),
        now=base_time,
    )

    assert detection.disappeared_candidates_seen == 1
    assert detection.disappeared_skipped_as_still_active == 0
    assert [candidate.market_id for candidate in detection.candidates] == [market_id]


def test_detect_disappeared_polymarket_skips_still_active_future_market(
    tmp_path: Path,
    base_time: datetime,
) -> None:
    archive = tmp_path / "forward_index"
    row = metadata_row(
        "polymarket",
        "poly-french-open",
        base_time - timedelta(hours=2),
        base_time + timedelta(days=30),
        "active",
        {"conditionId": "poly-french-open"},
        is_resolved=False,
        is_closed=False,
        resolution_outcome=None,
    )
    row["accepting_orders"] = True
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        [row],
        metadata_schema(),
    )

    detection = detect_disappeared_candidates(
        archive,
        venue="polymarket",
        seen=set(),
        now=base_time,
    )

    assert detection.disappeared_candidates_seen == 0
    assert detection.disappeared_skipped_as_still_active == 1
    assert detection.candidates == []


def test_detect_disappeared_kalshi_candidates_are_not_prefiltered(
    tmp_path: Path,
    base_time: datetime,
) -> None:
    archive = tmp_path / "forward_index"
    row = metadata_row(
        "kalshi",
        "KTEST-ACTIVE",
        base_time - timedelta(hours=2),
        base_time + timedelta(days=30),
        "active",
        {"ticker": "KTEST-ACTIVE"},
        is_resolved=False,
        is_closed=False,
        resolution_outcome=None,
    )
    row["accepting_orders"] = True
    write_table(
        archive / "market_metadata_snapshots" / "venue=kalshi" / "date=2026-05-16" / "part.parquet",
        [row],
        metadata_schema(),
    )

    detection = detect_disappeared_candidates(
        archive,
        venue="kalshi",
        seen=set(),
        now=base_time,
    )

    assert detection.disappeared_candidates_seen == 1
    assert detection.disappeared_skipped_as_still_active == 0
    assert [candidate.market_id for candidate in detection.candidates] == ["KTEST-ACTIVE"]


def test_detect_disappeared_polymarket_old_schema_is_included(
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
                "poly-old-schema",
                base_time - timedelta(hours=2),
                base_time + timedelta(days=30),
                "open",
                {"conditionId": "poly-old-schema"},
            )
        ],
        old_metadata_schema(),
    )

    detection = detect_disappeared_candidates(
        archive,
        venue="polymarket",
        seen=set(),
        now=base_time,
    )

    assert detection.disappeared_candidates_seen == 1
    assert detection.disappeared_skipped_as_still_active == 0
    assert [candidate.market_id for candidate in detection.candidates] == ["poly-old-schema"]


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
    write_disappeared_polymarket_rows(archive, now=now, count=50)
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
async def test_runner_disappeared_batch_matches_sequential_results(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    sequential_archive = tmp_path / "sequential" / "forward_index"
    concurrent_archive = tmp_path / "concurrent" / "forward_index"
    write_disappeared_polymarket_rows(sequential_archive, now=now, count=3)
    write_disappeared_polymarket_rows(concurrent_archive, now=now, count=3)
    sequential_output = tmp_path / "sequential" / "resolved"
    concurrent_output = tmp_path / "concurrent" / "resolved"

    sequential_runner = ResolutionWatcherRunner(
        settings=ResolutionWatcherSettings(
            source_dir=sequential_archive,
            output_dir=sequential_output,
            venues_enabled=["polymarket"],
            api_concurrency_limit=1,
        ),
        clients={"polymarket": ControlledApiClient()},
    )
    concurrent_runner = ResolutionWatcherRunner(
        settings=ResolutionWatcherSettings(
            source_dir=concurrent_archive,
            output_dir=concurrent_output,
            venues_enabled=["polymarket"],
            api_concurrency_limit=3,
        ),
        clients={"polymarket": ControlledApiClient()},
    )

    await sequential_runner.run_once()
    await concurrent_runner.run_once()

    assert resolved_market_ids(sequential_output) == resolved_market_ids(concurrent_output)
    assert sequential_runner.total_resolved_since_start == 3
    assert concurrent_runner.total_resolved_since_start == 3


@pytest.mark.asyncio
async def test_runner_disappeared_batch_caps_api_concurrency(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    archive = tmp_path / "forward_index"
    write_disappeared_polymarket_rows(archive, now=now, count=6)
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
        api_concurrency_limit=2,
    )
    client = ControlledApiClient(sleep_seconds=0.01)
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()

    assert client.fetch_count == 6
    assert client.max_in_flight == 2
    assert runner.total_resolved_since_start == 6


@pytest.mark.asyncio
async def test_runner_disappeared_batch_continues_after_candidate_exception(
    tmp_path: Path,
) -> None:
    now = datetime.now(tz=UTC)
    archive = tmp_path / "forward_index"
    write_disappeared_polymarket_rows(archive, now=now, count=3)
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
        api_concurrency_limit=3,
    )
    client = ControlledApiClient(fail_market_ids={"poly-disappeared-1"})
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()

    assert client.fetch_count == 3
    assert runner.total_resolved_since_start == 2
    assert resolved_market_ids(tmp_path / "resolved") == [
        "poly-disappeared-0",
        "poly-disappeared-2",
    ]


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


def test_resolution_watcher_settings_reads_global_api_concurrency_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PM_EDGE_API_CONCURRENCY_LIMIT", "20")

    settings = ResolutionWatcherSettings()

    assert settings.api_concurrency_limit == 20


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
    lookup = find_final_book_snapshot(
        source_archive,
        venue="polymarket",
        market_id="poly-1",
        before=base_time,
    )

    assert isinstance(lookup, FinalBookSnapshotLookup)
    assert lookup.snapshot.top_bid == 0.40
    assert lookup.snapshot.top_ask == 0.60
    assert lookup.snapshot.spread == 0.20
    assert lookup.post_anchor_rejected_count == 0


def test_find_final_book_snapshot_rejects_post_resolution_capture(
    tmp_path: Path, base_time: datetime
) -> None:
    archive = tmp_path / "forward_index"
    snapshot_path = (
        archive / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-16" / "part.parquet"
    )
    write_table(
        snapshot_path,
        [
            snapshot_row("polymarket", "poly-late", base_time - timedelta(minutes=10)),
            snapshot_row("polymarket", "poly-late", base_time + timedelta(seconds=10)),
        ],
        snapshot_schema(),
    )

    lookup = find_final_book_snapshot(
        archive,
        venue="polymarket",
        market_id="poly-late",
        before=base_time,
        lag_tolerance_seconds=5,
    )

    assert lookup.snapshot.timestamp_utc == base_time - timedelta(minutes=10)
    assert lookup.post_anchor_rejected_count == 1


def test_find_final_book_snapshot_clock_skew_tolerance_boundaries(
    tmp_path: Path, base_time: datetime
) -> None:
    archive = tmp_path / "forward_index"
    snapshot_path = (
        archive / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-16" / "part.parquet"
    )
    write_table(
        snapshot_path,
        [
            snapshot_row("polymarket", "poly-skew", base_time + timedelta(seconds=3)),
            snapshot_row("polymarket", "poly-skew", base_time + timedelta(seconds=7)),
        ],
        snapshot_schema(),
    )

    within_tolerance = find_final_book_snapshot(
        archive,
        venue="polymarket",
        market_id="poly-skew",
        before=base_time + timedelta(seconds=10),
        lag_tolerance_seconds=5,
    )
    assert within_tolerance.snapshot.timestamp_utc == base_time + timedelta(seconds=3)
    assert within_tolerance.post_anchor_rejected_count == 1

    outside_tolerance = find_final_book_snapshot(
        archive,
        venue="polymarket",
        market_id="poly-skew",
        before=base_time,
        lag_tolerance_seconds=5,
    )
    assert outside_tolerance.snapshot.timestamp_utc is None
    assert outside_tolerance.post_anchor_rejected_count == 2


@pytest.mark.asyncio
async def test_runner_main_path_rejects_post_resolution_snapshot(
    tmp_path: Path, base_time: datetime
) -> None:
    archive = tmp_path / "forward_index"
    resolution_time = base_time - timedelta(minutes=5)
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        [
            {
                **metadata_row(
                    "polymarket",
                    "poly-late-meta",
                    base_time,
                    base_time - timedelta(hours=1),
                    "closed",
                    {"closed": True, "conditionId": "poly-late-meta"},
                ),
                "resolution_timestamp_utc": resolution_time,
            }
        ],
        metadata_schema(),
    )
    write_table(
        archive / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-16" / "part.parquet",
        [
            snapshot_row("polymarket", "poly-late-meta", resolution_time - timedelta(minutes=15)),
            snapshot_row("polymarket", "poly-late-meta", resolution_time + timedelta(seconds=30)),
        ],
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
    assert rows[0]["final_snapshot_timestamp_utc"] == resolution_time - timedelta(minutes=15)
    assert runner.negative_lag_rejections_since_heartbeat == 1


class VenueTimestampedApiClient(FakeClient):
    """API client that returns a venue-published resolution timestamp."""

    def __init__(self, *, venue: str, venue_resolved_at_utc: datetime) -> None:
        super().__init__()
        self.venue = venue
        self.venue_resolved_at_utc = venue_resolved_at_utc
        self.observed_snapshots: list[FinalBookSnapshot] = []

    async def fetch_resolution_outcome(
        self,
        candidate: MarketResolutionCandidate,
        *,
        detected_at: datetime,
        final_snapshot: FinalBookSnapshot,
    ) -> ResolvedMarketOutcome | None:
        self.fetch_count += 1
        self.observed_snapshots.append(final_snapshot)
        return ResolvedMarketOutcome(
            venue=candidate.venue,
            market_id=candidate.market_id,
            resolution_timestamp_utc=detected_at,
            venue_resolved_at_utc=self.venue_resolved_at_utc,
            resolved_value=1.0,
            resolution_source=f"{candidate.venue}_api",
            final_top_bid=final_snapshot.top_bid,
            final_top_ask=final_snapshot.top_ask,
            final_spread=final_snapshot.spread,
            final_snapshot_timestamp_utc=final_snapshot.timestamp_utc,
            metadata_snapshot_id=candidate.metadata_snapshot_id,
        )


@pytest.mark.asyncio
async def test_runner_disappeared_path_uses_venue_resolved_at_utc(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    venue_resolved_at = now - timedelta(hours=2)
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
                "poly-disappeared-venue",
                now - timedelta(hours=3),
                now + timedelta(hours=1),
                "active",
                {"conditionId": "poly-disappeared-venue"},
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
        [
            snapshot_row(
                "polymarket",
                "poly-disappeared-venue",
                venue_resolved_at - timedelta(minutes=2),
            ),
            snapshot_row(
                "polymarket",
                "poly-disappeared-venue",
                venue_resolved_at + timedelta(minutes=30),
            ),
        ],
        snapshot_schema(),
    )
    settings = ResolutionWatcherSettings(
        source_dir=archive,
        output_dir=tmp_path / "resolved",
        venues_enabled=["polymarket"],
    )
    client = VenueTimestampedApiClient(venue="polymarket", venue_resolved_at_utc=venue_resolved_at)
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": client})

    await runner.run_once()

    rows = [
        row
        for path in (tmp_path / "resolved").glob("venue=polymarket/date=*/*.parquet")
        for row in pq.ParquetFile(path).read().to_pylist()
    ]
    assert len(rows) == 1
    assert rows[0]["final_snapshot_timestamp_utc"] == venue_resolved_at - timedelta(minutes=2)
    assert rows[0]["is_disappeared_detection"] is True
    assert client.observed_snapshots == [FinalBookSnapshot(None, None, None, None)]
    assert runner.negative_lag_rejections_since_heartbeat == 1


def test_resolution_watcher_settings_lag_tolerance_default_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ResolutionWatcherSettings().lag_tolerance_seconds == 5

    monkeypatch.setenv("PM_EDGE_RESOLUTION_WATCHER_LAG_TOLERANCE_SECONDS", "12")
    assert ResolutionWatcherSettings().lag_tolerance_seconds == 12
