import pandas as pd

from backtesting import BacktestConfig, PortfolioBacktester
from backtesting.portfolio_backtester import portfolio_config_from_backtest_config
from scripts.backtest import demo_signals


def test_portfolio_backtester_produces_equity_curve() -> None:
    config = portfolio_config_from_backtest_config(
        BacktestConfig(save_results=False, edge_threshold=0.02),
        kelly_fraction=0.4,
        max_exposure=0.2,
    )

    result = PortfolioBacktester(config).run(demo_signals())

    assert result.trades
    assert result.equity_curve
    assert "portfolio_final_equity" in result.report.metrics
    assert result.report.metrics["max_exposure"] <= 0.2


def test_portfolio_diagnostic_mode_ignores_zero_liquidity_cap() -> None:
    frame = pd.DataFrame(
        {
            "market_id": ["m1"],
            "as_of": [pd.Timestamp("2025-01-01", tz="UTC")],
            "resolved_at": [pd.Timestamp("2025-01-02", tz="UTC")],
            "venue": ["polymarket"],
            "market_probability": [0.45],
            "model_probability": [0.60],
            "confidence": [0.8],
            "outcome": [1],
            "liquidity": [0.0],
        }
    )
    normal_config = portfolio_config_from_backtest_config(
        BacktestConfig(save_results=False, edge_threshold=0.02),
        kelly_fraction=0.4,
        max_exposure=0.2,
    )
    diagnostic_config = portfolio_config_from_backtest_config(
        BacktestConfig(save_results=False, edge_threshold=0.02),
        kelly_fraction=0.4,
        max_exposure=0.2,
        diagnostic_mode=True,
    )

    normal = PortfolioBacktester(normal_config).run(frame)
    diagnostic = PortfolioBacktester(diagnostic_config).run(frame)

    assert not normal.trades
    assert normal.diagnostics["liquidity_cap_rejected"] == 1
    assert diagnostic.trades
    assert diagnostic.diagnostics["diagnostic_mode"] is True
