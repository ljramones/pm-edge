"""Public execution simulator entry points."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from .assumptions import run_all
from .book_lookup import BookLookup
from .config import SimulatorConfig
from .fill_logic import simulate_fill
from .types import FillOutcome, OrderSpec


def simulate_order(
    market_id: str,
    venue: str,
    side: Literal["buy", "sell"],
    size: float,
    limit_price: float | None,
    submitted_at: datetime,
    archive_path: Path,
    config: SimulatorConfig | None = None,
) -> FillOutcome:
    """Simulate one historical order against a local forward-index archive."""

    order = OrderSpec(
        market_id=market_id,
        venue=venue,
        side=side,
        size=size,
        limit_price=limit_price,
        submitted_at=submitted_at,
    )
    lookup = BookLookup(archive_path)
    try:
        snapshot = lookup.get_snapshot(
            venue=venue,
            market_id=market_id,
            submitted_at=submitted_at,
        )
        return simulate_fill(order, snapshot, config or SimulatorConfig())
    finally:
        lookup.close()


def simulate_strategy(
    orders: list[OrderSpec],
    archive_path: Path,
    config: SimulatorConfig | None = None,
    *,
    print_assumptions: bool = True,
) -> list[FillOutcome]:
    """Simulate a batch of orders sequentially against a local archive."""

    active_config = config or SimulatorConfig()
    if print_assumptions:
        print(run_all(archive_path).to_text())
    lookup = BookLookup(archive_path)
    try:
        outcomes: list[FillOutcome] = []
        for order in orders:
            snapshot = lookup.get_snapshot(
                venue=order.venue,
                market_id=order.market_id,
                submitted_at=order.submitted_at,
            )
            outcomes.append(simulate_fill(order, snapshot, active_config))
        return outcomes
    finally:
        lookup.close()
