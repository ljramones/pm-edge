from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from execution_simulator import OrderSpec, simulate_order, simulate_strategy


def test_simulate_order_end_to_end(archive_path: Path, base_time: datetime) -> None:
    outcome = simulate_order(
        market_id="market-1",
        venue="polymarket",
        side="buy",
        size=5.0,
        limit_price=None,
        submitted_at=base_time + timedelta(seconds=30),
        archive_path=archive_path,
    )

    assert outcome.status == "filled"
    assert outcome.filled_price == 0.51


def test_simulate_strategy_returns_one_outcome_per_order(
    archive_path: Path,
    base_time: datetime,
) -> None:
    orders = [
        OrderSpec(
            market_id="market-1",
            venue="polymarket",
            side="buy",
            size=1.0,
            limit_price=None,
            submitted_at=base_time + timedelta(seconds=index),
        )
        for index in range(10)
    ]

    outcomes = simulate_strategy(orders, archive_path, print_assumptions=False)

    assert len(outcomes) == 10
    assert {outcome.status for outcome in outcomes} == {"filled"}
