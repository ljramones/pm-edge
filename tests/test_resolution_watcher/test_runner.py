from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from data.resolution_watcher.runner import (
    ResolutionWatcherRunner,
    detect_resolution_candidates,
    find_final_book_snapshot,
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
