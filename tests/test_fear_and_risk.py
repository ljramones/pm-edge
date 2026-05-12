from __future__ import annotations

import pandas as pd

from execution import MonteCarloRuinSimulator
from features import FearLayerRouter, FearSnapshot
from strategies import StructuralScanner


def test_fear_layer_routes_liquid_market() -> None:
    router = FearLayerRouter()

    state = router.evaluate(
        market_id="btc",
        liquidity=1_000_000,
        volume=500_000,
        spread=0.02,
        fear=FearSnapshot(vix=30, cnn_fear_greed=25, crypto_fear_greed=20),
    )

    assert state.route is True
    assert state.sizing_multiplier > 0


def test_monte_carlo_ruin_simulator_reports_survival() -> None:
    result = MonteCarloRuinSimulator(simulations=100, seed=1).run(
        pd.Series([10.0, -5.0, 12.0, -3.0])
    )

    assert 0 <= result.ruin_probability <= 1
    assert result.periods == 4


def test_monte_carlo_ruin_simulator_handles_no_trades() -> None:
    result = MonteCarloRuinSimulator(starting_capital=10_000, simulations=100, seed=1).run(
        pd.Series(dtype=float)
    )

    assert result.ruin_probability == 0
    assert result.median_final_equity == 10_000


def test_structural_scanner_detects_sum_less_than_one() -> None:
    frame = pd.DataFrame(
        {
            "event_cluster": ["e1", "e1"],
            "market_id": ["a", "b"],
            "market_probability": [0.45, 0.50],
            "liquidity": [20_000, 25_000],
        }
    )

    opportunities = StructuralScanner(min_edge=0.02).scan(frame)

    assert opportunities
    assert opportunities[0].opportunity_type == "sum_lt_1"
