"""Conservative v0 fill logic."""

from __future__ import annotations

from datetime import timedelta

from .config import SimulatorConfig
from .types import BookSnapshot, FillOutcome, OrderSpec, OrderStatus


def simulate_fill(
    order: OrderSpec,
    book: BookSnapshot | None,
    config: SimulatorConfig,
) -> FillOutcome:
    """Simulate one order against one point-in-time book snapshot."""

    if book is None:
        return _unfilled(order, ["missing_book_state"])

    age_seconds = book.age_at(order.submitted_at)
    if age_seconds > config.max_book_age_seconds:
        return _unfilled(order, ["stale_book_state"])

    if order.side == "buy":
        return _simulate_buy(order, book, config)
    return _simulate_sell(order, book, config)


def _simulate_buy(
    order: OrderSpec,
    book: BookSnapshot,
    config: SimulatorConfig,
) -> FillOutcome:
    if book.top_ask is None or not book.ask_levels:
        return _unfilled(order, ["empty_book_side"])
    if config.require_complete_top_book and book.top_bid is None:
        return _unfilled(order, ["incomplete_top_book"])
    if order.limit_price is None or order.limit_price >= book.top_ask:
        return _marketable_fill(order, book, book.top_ask, book.ask_levels[0]["size"], config)
    if book.top_bid is not None and order.limit_price > book.top_bid:
        raise ValueError(
            "Buy limit is inside the spread/better than current top bid; "
            "v0 does not model queue placement for improving resting orders."
        )
    return _unfilled(order, ["resting_order_worst_case_queue"])


def _simulate_sell(
    order: OrderSpec,
    book: BookSnapshot,
    config: SimulatorConfig,
) -> FillOutcome:
    if book.top_bid is None or not book.bid_levels:
        return _unfilled(order, ["empty_book_side"])
    if config.require_complete_top_book and book.top_ask is None:
        return _unfilled(order, ["incomplete_top_book"])
    if order.limit_price is None or order.limit_price <= book.top_bid:
        return _marketable_fill(order, book, book.top_bid, book.bid_levels[0]["size"], config)
    if book.top_ask is not None and order.limit_price < book.top_ask:
        raise ValueError(
            "Sell limit is inside the spread/better than current top ask; "
            "v0 does not model queue placement for improving resting orders."
        )
    return _unfilled(order, ["resting_order_worst_case_queue"])


def _marketable_fill(
    order: OrderSpec,
    book: BookSnapshot,
    fill_price: float,
    available_size: float,
    config: SimulatorConfig,
) -> FillOutcome:
    if available_size <= 0:
        return _unfilled(order, ["empty_book_side"])
    filled_size = min(order.size, available_size)
    status: OrderStatus = "filled" if filled_size >= order.size else "partial"
    reference_price = order.limit_price if order.limit_price is not None else book.mid
    slippage = None if reference_price is None else fill_price - reference_price
    fees = filled_size * fill_price * config.taker_fee_bps / 10_000
    assumptions = ["marketable_full_spread_cross"]
    if status == "partial":
        assumptions.append("top_level_only_partial")
    return FillOutcome(
        status=status,
        requested_size=order.size,
        filled_size=filled_size,
        filled_price=fill_price,
        slippage=slippage,
        time_to_fill=timedelta(seconds=0),
        fees=fees,
        assumptions_triggered=assumptions,
        market_id=order.market_id,
        venue=order.venue,
        side=order.side,
        submitted_at=order.submitted_at,
        fill_timestamp=order.submitted_at,
    )


def _unfilled(order: OrderSpec, assumptions: list[str]) -> FillOutcome:
    return FillOutcome(
        status="unfilled",
        requested_size=order.size,
        assumptions_triggered=assumptions,
        market_id=order.market_id,
        venue=order.venue,
        side=order.side,
        submitted_at=order.submitted_at,
    )
