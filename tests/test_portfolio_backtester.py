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
