from __future__ import annotations

from datetime import UTC, datetime

import pytest

from execution_simulator.config import SimulatorConfig
from execution_simulator.fill_logic import simulate_fill
from execution_simulator.types import BookSnapshot, OrderSpec


def test_marketable_buy_fills_at_top_ask() -> None:
    order = order_spec(side="buy", size=5.0, limit_price=None)

    outcome = simulate_fill(order, normal_book(), SimulatorConfig())

    assert outcome.status == "filled"
    assert outcome.filled_size == 5.0
    assert outcome.filled_price == 0.51
    assert outcome.slippage == pytest.approx(0.01)
    assert outcome.fees == pytest.approx(0.01275)
    assert outcome.assumptions_triggered == ["marketable_full_spread_cross"]


def test_marketable_sell_fills_at_top_bid() -> None:
    order = order_spec(side="sell", size=4.0, limit_price=None)

    outcome = simulate_fill(order, normal_book(), SimulatorConfig())

    assert outcome.status == "filled"
    assert outcome.filled_size == 4.0
    assert outcome.filled_price == 0.49
    assert outcome.slippage == pytest.approx(-0.01)


def test_marketable_order_partially_fills_only_level_one() -> None:
    order = order_spec(side="buy", size=10.0, limit_price=None)

    outcome = simulate_fill(order, normal_book(), SimulatorConfig())

    assert outcome.status == "partial"
    assert outcome.filled_size == 8.0
    assert outcome.assumptions_triggered == [
        "marketable_full_spread_cross",
        "top_level_only_partial",
    ]


def test_marketable_order_in_empty_book_is_unfilled() -> None:
    order = order_spec(side="buy", size=1.0, limit_price=None)
    book = normal_book(
        ask_levels=[],
        top_ask=None,
        mid=None,
        spread=None,
    )

    outcome = simulate_fill(order, book, SimulatorConfig())

    assert outcome.status == "unfilled"
    assert outcome.assumptions_triggered == ["empty_book_side"]


def test_resting_order_at_worse_price_is_unfilled() -> None:
    order = order_spec(side="buy", size=1.0, limit_price=0.48)

    outcome = simulate_fill(order, normal_book(), SimulatorConfig())

    assert outcome.status == "unfilled"
    assert outcome.assumptions_triggered == ["resting_order_worst_case_queue"]


def test_resting_order_that_improves_top_raises() -> None:
    order = order_spec(side="buy", size=1.0, limit_price=0.50)

    with pytest.raises(ValueError, match="inside the spread"):
        simulate_fill(order, normal_book(), SimulatorConfig())


def test_stale_book_state_is_unfilled() -> None:
    order = order_spec(
        side="buy",
        size=1.0,
        limit_price=None,
        submitted_at=datetime(2026, 5, 15, 12, 2, 1, tzinfo=UTC),
    )

    outcome = simulate_fill(order, normal_book(), SimulatorConfig(max_book_age_seconds=60))

    assert outcome.status == "unfilled"
    assert outcome.assumptions_triggered == ["stale_book_state"]


def order_spec(
    *,
    side: str,
    size: float,
    limit_price: float | None,
    submitted_at: datetime | None = None,
) -> OrderSpec:
    return OrderSpec(
        market_id="market-1",
        venue="polymarket",
        side=side,  # type: ignore[arg-type]
        size=size,
        limit_price=limit_price,
        submitted_at=submitted_at or datetime(2026, 5, 15, 12, 0, 5, tzinfo=UTC),
    )


def normal_book(
    *,
    ask_levels: list[dict[str, float]] | None = None,
    top_ask: float | None = 0.51,
    mid: float | None = 0.50,
    spread: float | None = 0.02,
) -> BookSnapshot:
    return BookSnapshot(
        venue="polymarket",
        market_id="market-1",
        timestamp_utc=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
        bid_levels=[{"price": 0.49, "size": 10.0}],
        ask_levels=[{"price": 0.51, "size": 8.0}] if ask_levels is None else ask_levels,
        top_bid=0.49,
        top_ask=top_ask,
        mid=mid,
        spread=spread,
        snapshot_source="websocket",
    )
