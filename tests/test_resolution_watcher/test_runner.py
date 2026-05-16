from __future__ import annotations

from datetime import datetime
from pathlib import Path

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


class FakeClient:
    venue = "polymarket"

    async def fetch_resolution_outcome(
        self,
        candidate: MarketResolutionCandidate,
        *,
        detected_at: datetime,
        final_snapshot: FinalBookSnapshot,
    ) -> ResolvedMarketOutcome | None:
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
    runner = ResolutionWatcherRunner(settings=settings, clients={"polymarket": FakeClient()})

    await runner.run_once()

    assert runner.total_resolved_since_start == 1
    assert ("polymarket", "poly-1") in runner.seen_resolutions
    assert list((tmp_path / "resolved").glob("venue=polymarket/date=*/*.parquet"))


@pytest.mark.asyncio
async def test_runner_does_not_crash_on_per_venue_error(
    source_archive: Path,
    tmp_path: Path,
) -> None:
    settings = ResolutionWatcherSettings(
        source_dir=source_archive,
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
    candidates = detect_resolution_candidates(
        source_archive,
        venue="polymarket",
        seen=set(),
        now=base_time + datetime.resolution,
    )

    assert [candidate.market_id for candidate in candidates] == ["poly-1"]


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
