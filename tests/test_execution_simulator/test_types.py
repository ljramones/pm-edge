from __future__ import annotations

from datetime import UTC, datetime, timedelta

from execution_simulator.types import FillOutcome, OrderSpec


def test_order_spec_round_trips_to_dict() -> None:
    order = OrderSpec(
        market_id="market-1",
        venue="polymarket",
        side="buy",
        size=5.0,
        limit_price=0.51,
        submitted_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
    )

    restored = OrderSpec.from_dict(order.to_dict())

    assert restored == order


def test_fill_outcome_round_trips_to_dict() -> None:
    outcome = FillOutcome(
        status="filled",
        requested_size=5.0,
        filled_size=5.0,
        filled_price=0.51,
        slippage=0.01,
        time_to_fill=timedelta(seconds=0),
        fees=0.01275,
        assumptions_triggered=["marketable_full_spread_cross"],
        market_id="market-1",
        venue="polymarket",
        side="buy",
        submitted_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
        fill_timestamp=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
    )

    restored = FillOutcome.from_dict(outcome.to_dict())

    assert restored == outcome
