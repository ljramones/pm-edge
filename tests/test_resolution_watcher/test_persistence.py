from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from data.resolution_watcher.persistence import ResolutionOutcomeWriter
from data.resolution_watcher.schema import ResolvedMarketOutcome


@pytest.mark.asyncio
async def test_resolution_outcome_writer_round_trip(tmp_path: Path) -> None:
    writer = ResolutionOutcomeWriter(tmp_path)
    outcome = ResolvedMarketOutcome(
        venue="polymarket",
        market_id="poly-1",
        resolution_timestamp_utc=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
        venue_resolved_at_utc=None,
        resolved_value=1.0,
        resolution_source="polymarket_api",
        final_top_bid=0.99,
        final_top_ask=1.0,
        final_spread=0.01,
        final_snapshot_timestamp_utc=datetime(2026, 5, 16, 11, 59, tzinfo=UTC),
        metadata_snapshot_id="id-1",
    )

    written = await writer.write([outcome])

    assert written == 1
    paths = await asyncio.to_thread(
        lambda: list(tmp_path.glob("venue=polymarket/date=2026-05-16/*.parquet"))
    )
    assert len(paths) == 1
    rows = pq.ParquetFile(paths[0]).read().to_pylist()
    assert rows[0]["market_id"] == "poly-1"
    assert rows[0]["resolved_value"] == 1.0
