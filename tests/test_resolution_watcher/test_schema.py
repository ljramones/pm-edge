from __future__ import annotations

from datetime import UTC, datetime

from data.resolution_watcher.schema import ResolvedMarketOutcome


def test_resolved_market_outcome_round_trips_record() -> None:
    outcome = ResolvedMarketOutcome(
        venue="polymarket",
        market_id="poly-1",
        resolution_timestamp_utc=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
        venue_resolved_at_utc=datetime(2026, 5, 16, 11, 59, tzinfo=UTC),
        resolved_value=1.0,
        resolution_source="polymarket_api",
        final_top_bid=0.99,
        final_top_ask=1.0,
        final_spread=0.01,
        final_snapshot_timestamp_utc=datetime(2026, 5, 16, 11, 58, tzinfo=UTC),
        metadata_snapshot_id="polymarket:poly-1:2026-05-16T12:00:00+00:00",
    )

    restored = ResolvedMarketOutcome.from_record(outcome.to_record())

    assert restored == outcome
