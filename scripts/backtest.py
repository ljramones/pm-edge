"""Run deterministic strategy backtests."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtesting import BacktestConfig, Backtester, FeeModel, PortfolioBacktester, WalkForwardConfig
from backtesting.portfolio_backtester import portfolio_config_from_backtest_config
from core import get_settings
from utils import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest edge signals.")
    parser.add_argument("--strategy", default="gbdt_v1")
    parser.add_argument("--period", help="Inclusive period in YYYY-MM-DD:YYYY-MM-DD format.")
    parser.add_argument(
        "--signals", type=Path, help="CSV/Parquet file with historical signal rows."
    )
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--edge-threshold", type=float, default=0.02)
    parser.add_argument("--stake", type=float, default=100.0)
    parser.add_argument("--slippage-bps", type=float, default=15.0)
    parser.add_argument("--kalshi-fee-bps", type=float, default=7.0)
    parser.add_argument("--polymarket-fee-bps", type=float, default=0.0)
    parser.add_argument("--portfolio", action="store_true")
    parser.add_argument("--kelly-fraction", type=float, default=0.4)
    parser.add_argument("--max-exposure", type=float, default=0.2)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    period_start, period_end = parse_period(args.period)
    signals = load_signals(args.signals)
    config = BacktestConfig(
        strategy_name=args.strategy,
        edge_threshold=args.edge_threshold,
        stake=args.stake,
        fee_model=FeeModel(
            polymarket_fee_bps=args.polymarket_fee_bps,
            kalshi_fee_bps=args.kalshi_fee_bps,
            slippage_bps=args.slippage_bps,
        ),
        walk_forward=WalkForwardConfig(min_train_observations=30 if args.walk_forward else 10**9),
        save_results=not args.no_save,
    )
    if args.portfolio:
        portfolio_config = portfolio_config_from_backtest_config(
            config,
            kelly_fraction=args.kelly_fraction,
            max_exposure=args.max_exposure,
        )
        portfolio_result = PortfolioBacktester(portfolio_config).run(
            signals,
            period_start=period_start,
            period_end=period_end,
        )
        print_summary(portfolio_result.report.metrics, portfolio_result.rubric.grade)
        return

    result = Backtester(config=config, settings=settings).run(
        signals,
        period_start=period_start,
        period_end=period_end,
    )
    print_summary(result.report.metrics, result.rubric.grade)


def load_signals(path: Path | None) -> pd.DataFrame:
    """Load historical signal rows from disk or return a deterministic demo fixture."""

    if path is None:
        return demo_signals()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def parse_period(period: str | None) -> tuple[datetime | None, datetime | None]:
    if not period:
        return None, None
    start, end = period.split(":", maxsplit=1)
    return datetime.fromisoformat(start), datetime.fromisoformat(end)


def print_summary(metrics: dict[str, float], grade: str) -> None:
    print(f"Rubric: {grade}")
    for key in [
        "bet_count",
        "mean_edge",
        "brier_score",
        "log_loss",
        "net_pnl",
        "return_on_allocated_capital",
        "sharpe",
        "sortino",
        "profit_factor",
        "max_drawdown",
        "portfolio_final_equity",
        "portfolio_return",
        "portfolio_sharpe",
        "portfolio_max_drawdown",
        "portfolio_calmar",
        "max_exposure",
    ]:
        print(f"{key:>28}: {metrics.get(key, 0.0):.4f}")


def demo_signals() -> pd.DataFrame:
    """Return deterministic demo signals for smoke tests and local CLI runs."""

    dates = pd.date_range("2025-01-01", periods=80, freq="7D", tz="UTC")
    rows = []
    for index, as_of in enumerate(dates):
        market_probability = 0.42 + (index % 7) * 0.015
        model_probability = market_probability + (0.04 if index % 3 else -0.03)
        outcome = int(model_probability > 0.5 or index % 5 == 0)
        rows.append(
            {
                "market_id": f"demo-{index}",
                "category": "crypto" if index % 2 else "election",
                "as_of": as_of,
                "resolved_at": as_of + pd.Timedelta(days=14),
                "venue": "polymarket" if index % 2 else "kalshi",
                "market_probability": market_probability,
                "model_probability": model_probability,
                "outcome": outcome,
            }
        )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
