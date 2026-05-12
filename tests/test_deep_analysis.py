from __future__ import annotations

import pandas as pd

from backtesting.deep_analysis import DeepRunArtifact, analyze_deep_backtest


def test_analyze_deep_backtest_returns_diagnostic_tables() -> None:
    bets = pd.DataFrame(
        {
            "market_id": ["m1", "m2", "m3"],
            "category": ["crypto", "politics", "crypto"],
            "as_of": pd.date_range("2025-01-01", periods=3, tz="UTC"),
            "resolved_at": pd.date_range("2025-01-08", periods=3, tz="UTC"),
            "market_probability": [0.45, 0.50, 0.55],
            "model_probability": [0.55, 0.46, 0.62],
            "edge": [0.10, -0.04, 0.07],
            "stake": [100.0, 80.0, 90.0],
            "slippage": [0.001, 0.001, 0.001],
            "pnl": [80.0, -80.0, 60.0],
            "return_on_capital": [0.8, -1.0, 0.67],
            "outcome": [1, 1, 1],
            "confidence": [0.8, 0.3, 0.6],
        }
    )
    artifact = DeepRunArtifact(
        name="base",
        metrics={"bet_count": 3.0, "net_pnl": 60.0, "brier_score": 0.20},
        rubric={"grade": "Fail", "go_no_go": "No-Go"},
        bets=bets,
    )

    result = analyze_deep_backtest([artifact])

    assert result.summary["base"]["net_pnl"] == 60.0
    assert not result.calibration.empty
    assert not result.by_category.empty
    assert not result.failures.empty
    assert not result.bootstrap_intervals.empty
    assert not result.rubric_failures.empty
