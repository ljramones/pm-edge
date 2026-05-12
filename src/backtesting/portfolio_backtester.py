"""Portfolio-level backtesting with fractional Kelly allocation."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import uuid4

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtesting.backtester import BacktestConfig, FeeModel, normalize_signal_frame
from backtesting.metrics import BacktestMetrics, EvaluationReport, max_drawdown
from backtesting.rubric import EvaluationRubric, RubricDecision
from core.models import Venue
from execution import KellyFractionalPortfolio, KellyPortfolioConfig
from strategies import EdgeSignal
from utils.logging import get_logger

logger = get_logger(__name__)


class PortfolioBacktestConfig(BaseModel):
    """Portfolio simulation settings."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str = "gbdt_v1"
    starting_capital: float = 10_000.0
    rebalance_frequency: str = "1D"
    edge_threshold: float = 0.02
    fee_model: FeeModel = Field(default_factory=FeeModel)
    kelly: KellyPortfolioConfig = Field(default_factory=KellyPortfolioConfig)


class PortfolioBacktestResult(BaseModel):
    """Portfolio-level backtest result."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    trades: list[dict[str, object]]
    equity_curve: list[dict[str, object]]
    report: EvaluationReport
    rubric: RubricDecision

    def trades_frame(self) -> pd.DataFrame:
        """Return simulated portfolio trades."""

        return pd.DataFrame(self.trades)

    def equity_frame(self) -> pd.DataFrame:
        """Return portfolio equity curve."""

        return pd.DataFrame(self.equity_curve)


class PortfolioBacktester:
    """Simulate periodic rebalancing using fractional Kelly targets."""

    def __init__(self, config: PortfolioBacktestConfig | None = None) -> None:
        self.config = config or PortfolioBacktestConfig()
        self.allocator = KellyFractionalPortfolio(self.config.kelly)
        self.metrics = BacktestMetrics()
        self.rubric = EvaluationRubric()

    def run(
        self,
        signals: pd.DataFrame,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> PortfolioBacktestResult:
        """Run a portfolio backtest from historical signal rows."""

        run_id = str(uuid4())
        frame = normalize_signal_frame(signals)
        if period_start is not None:
            frame = frame[frame["as_of"] >= pd.Timestamp(period_start)]
        if period_end is not None:
            frame = frame[frame["as_of"] <= pd.Timestamp(period_end)]
        if frame.empty:
            report = EvaluationReport()
            return PortfolioBacktestResult(
                run_id=run_id,
                trades=[],
                equity_curve=[],
                report=report,
                rubric=self.rubric.evaluate(report.metrics),
            )

        capital = self.config.starting_capital
        trades: list[dict[str, object]] = []
        equity_curve: list[dict[str, object]] = []
        for rebalance_time, group in frame.groupby(
            pd.Grouper(key="as_of", freq=self.config.rebalance_frequency)
        ):
            if group.empty:
                continue
            signals_for_period = [
                self._row_to_signal(row) for row in group.to_dict(orient="records")
            ]
            liquidity = {
                str(row["market_id"]): float(cast(float | int | str, row.get("liquidity", capital)))
                for row in group.to_dict(orient="records")
            }
            targets = self.allocator.allocate(
                signals_for_period, capital=capital, liquidity=liquidity
            )
            turnover = sum(target.target_notional for target in targets)
            period_pnl = 0.0
            for target in targets:
                row = group[group["market_id"] == target.market_id].iloc[0].to_dict()
                trade = self._simulate_target(row, target_notional=target.target_notional)
                trades.append(trade)
                period_pnl += float(cast(float | int | str, trade["pnl"]))
            capital += period_pnl
            equity_curve.append(
                {
                    "as_of": rebalance_time,
                    "equity": capital,
                    "period_pnl": period_pnl,
                    "turnover": turnover,
                    "exposure": turnover / max(capital, 1e-9),
                    "position_count": len(targets),
                }
            )

        trades_frame = pd.DataFrame(trades)
        report = self.metrics.evaluate(trades_frame)
        if equity_curve:
            equity = pd.DataFrame(equity_curve)
            report.metrics.update(
                portfolio_metrics(equity, starting_capital=self.config.starting_capital)
            )
        decision = self.rubric.evaluate(report.metrics)
        logger.info(
            "portfolio_backtest_completed",
            run_id=run_id,
            trades=len(trades),
            grade=decision.grade,
        )
        return PortfolioBacktestResult(
            run_id=run_id,
            trades=trades,
            equity_curve=equity_curve,
            report=report,
            rubric=decision,
        )

    def _row_to_signal(self, row: dict[str, object]) -> EdgeSignal:
        market_probability = float(cast(float | int | str, row["market_probability"]))
        model_probability = float(cast(float | int | str, row["model_probability"]))
        edge = model_probability - market_probability
        return EdgeSignal(
            market_id=str(row["market_id"]),
            market_prob=market_probability,
            model_prob=model_probability,
            edge=edge,
            confidence=float(
                cast(float | int | str, row.get("confidence", min(abs(edge) / 0.1, 1.0)))
            ),
            reasoning=["historical signal row"],
            features={
                "top_book_liquidity": float(cast(float | int | str, row.get("liquidity", 0.0)))
            },
        )

    def _simulate_target(
        self, row: dict[str, object], *, target_notional: float
    ) -> dict[str, object]:
        venue = Venue(str(row.get("venue", Venue.POLYMARKET.value)))
        market_probability = float(cast(float | int | str, row["market_probability"]))
        model_probability = float(cast(float | int | str, row["model_probability"]))
        outcome = int(cast(float | int | str, row["outcome"]))
        edge = model_probability - market_probability
        direction = 1 if edge > 0 else -1
        raw_entry = market_probability if direction > 0 else 1 - market_probability
        slippage = raw_entry * self.config.fee_model.slippage_rate
        entry_price = min(max(raw_entry + slippage, 0.001), 0.999)
        fee = target_notional * self.config.fee_model.fee_rate(venue)
        wins = outcome == 1 if direction > 0 else outcome == 0
        gross_pnl = (
            target_notional * ((1 - entry_price) / entry_price) if wins else -target_notional
        )
        pnl = gross_pnl - fee
        return {
            "market_id": row["market_id"],
            "category": row.get("category"),
            "as_of": row["as_of"],
            "resolved_at": row["resolved_at"],
            "venue": venue.value,
            "market_probability": market_probability,
            "model_probability": model_probability,
            "edge": edge,
            "stake": target_notional,
            "entry_price": entry_price,
            "slippage": slippage,
            "fee": fee,
            "outcome": outcome,
            "pnl": pnl,
            "return_on_capital": pnl / max(target_notional, 1e-9),
        }


def portfolio_metrics(equity_curve: pd.DataFrame, *, starting_capital: float) -> dict[str, float]:
    """Return portfolio-level equity, drawdown, turnover, and exposure metrics."""

    if equity_curve.empty:
        return {}
    returns = (
        equity_curve["equity"]
        .pct_change()
        .fillna((equity_curve["equity"].iloc[0] - starting_capital) / starting_capital)
    )
    pnl = equity_curve["period_pnl"].astype(float)
    drawdown = max_drawdown(pnl)
    equity_drawdown = (
        equity_curve["equity"].astype(float) - equity_curve["equity"].astype(float).cummax()
    )
    equity_drawdown_pct = float((equity_drawdown / starting_capital).min())
    return {
        "portfolio_final_equity": float(equity_curve["equity"].iloc[-1]),
        "portfolio_return": float(equity_curve["equity"].iloc[-1] / starting_capital - 1),
        "portfolio_sharpe": (
            float(returns.mean() / returns.std(ddof=0) * (len(returns) ** 0.5))
            if returns.std(ddof=0)
            else 0.0
        ),
        "portfolio_max_drawdown": drawdown,
        "portfolio_max_drawdown_pct": equity_drawdown_pct,
        "portfolio_calmar": float(pnl.sum() / abs(drawdown)) if drawdown else 0.0,
        "average_turnover": float(equity_curve["turnover"].mean()),
        "max_exposure": float(equity_curve["exposure"].max()),
    }


def portfolio_config_from_backtest_config(
    config: BacktestConfig,
    *,
    kelly_fraction: float,
    max_exposure: float,
    quarter_kelly: bool = False,
    min_post_cost_edge: float = 0.0,
) -> PortfolioBacktestConfig:
    """Create portfolio config from existing independent-bet config."""

    return PortfolioBacktestConfig(
        strategy_name=config.strategy_name,
        starting_capital=config.starting_capital,
        edge_threshold=config.edge_threshold,
        fee_model=config.fee_model,
        kelly=KellyPortfolioConfig(
            kelly_fraction=kelly_fraction,
            max_total_exposure=max_exposure,
            min_edge=config.edge_threshold,
            quarter_kelly=quarter_kelly,
            min_cash_buffer=0.30 if quarter_kelly else 0.0,
            min_post_cost_edge=min_post_cost_edge,
        ),
    )
