"""Backtest predictive and economic evaluation metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from sklearn.metrics import log_loss


class CalibrationBucket(BaseModel):
    """Reliability-bucket calibration statistics."""

    model_prob_mean: float
    outcome_rate: float
    count: int
    abs_error: float


class EvaluationReport(BaseModel):
    """Comprehensive backtest metric report."""

    model_config = ConfigDict(frozen=True)

    metrics: dict[str, float] = Field(default_factory=dict)
    calibration: list[CalibrationBucket] = Field(default_factory=list)
    by_category: dict[str, dict[str, float]] = Field(default_factory=dict)
    edge_decay: dict[str, float] = Field(default_factory=dict)


@dataclass(frozen=True)
class MetricConfig:
    """Metric calculation settings."""

    calibration_bins: int = 10
    risk_free_rate: float = 0.0


class BacktestMetrics:
    """Compute predictive power, economic value, and robustness metrics."""

    def __init__(self, config: MetricConfig | None = None) -> None:
        self.config = config or MetricConfig()

    def evaluate(self, bets: pd.DataFrame) -> EvaluationReport:
        """Evaluate simulated bets."""

        if bets.empty:
            return EvaluationReport()

        frame = bets.copy()
        frame["model_probability"] = frame["model_probability"].astype(float).clip(0.001, 0.999)
        frame["market_probability"] = frame["market_probability"].astype(float).clip(0.001, 0.999)
        frame["outcome"] = frame["outcome"].astype(int)
        frame["pnl"] = frame["pnl"].astype(float)
        frame["stake"] = frame["stake"].astype(float)
        returns = frame["return_on_capital"].astype(float)

        metrics = {
            "bet_count": float(len(frame)),
            "mean_edge": float(frame["edge"].astype(float).mean()),
            "brier_score": brier_score(frame["model_probability"], frame["outcome"]),
            "log_loss": float(
                log_loss(frame["outcome"], frame["model_probability"], labels=[0, 1])
            ),
            "spearman_edge_outcome": _safe_corr(frame["edge"], frame["outcome"], method="spearman"),
            "kendall_edge_outcome": _safe_corr(frame["edge"], frame["outcome"], method="kendall"),
            "net_pnl": float(frame["pnl"].sum()),
            "total_stake": float(frame["stake"].sum()),
            "return_on_allocated_capital": float(
                frame["pnl"].sum() / max(frame["stake"].sum(), 1e-9)
            ),
            "sharpe": sharpe_ratio(returns),
            "sortino": sortino_ratio(returns),
            "profit_factor": profit_factor(frame["pnl"]),
            "max_drawdown": max_drawdown(frame["pnl"]),
            "calmar": calmar_ratio(frame["pnl"]),
        }
        metrics.update(hit_rates(frame))

        return EvaluationReport(
            metrics=metrics,
            calibration=calibration_buckets(frame, bins=self.config.calibration_bins),
            by_category=performance_by_category(frame),
            edge_decay=edge_decay_profile(frame),
        )


def brier_score(probabilities: pd.Series, outcomes: pd.Series) -> float:
    """Return Brier score."""

    return float(np.mean((probabilities.astype(float) - outcomes.astype(float)) ** 2))


def calibration_buckets(frame: pd.DataFrame, *, bins: int = 10) -> list[CalibrationBucket]:
    """Return reliability diagram bucket stats."""

    data = frame.copy()
    data["bucket"] = pd.cut(
        data["model_probability"], bins=np.linspace(0, 1, bins + 1), include_lowest=True
    )
    output: list[CalibrationBucket] = []
    for _bucket, group in data.groupby("bucket", observed=True):
        if group.empty:
            continue
        model_mean = float(group["model_probability"].mean())
        outcome_rate = float(group["outcome"].mean())
        output.append(
            CalibrationBucket(
                model_prob_mean=model_mean,
                outcome_rate=outcome_rate,
                count=len(group),
                abs_error=abs(model_mean - outcome_rate),
            )
        )
    return output


def hit_rates(
    frame: pd.DataFrame, thresholds: tuple[float, ...] = (0.01, 0.02, 0.04, 0.08)
) -> dict[str, float]:
    """Return hit rates at absolute edge thresholds."""

    output: dict[str, float] = {}
    for threshold in thresholds:
        subset = frame[frame["edge"].astype(float).abs() >= threshold]
        output[f"hit_rate_edge_ge_{threshold:.0%}"] = (
            float((subset["pnl"] > 0).mean()) if not subset.empty else 0.0
        )
    return output


def sharpe_ratio(returns: pd.Series) -> float:
    """Return per-bet Sharpe ratio."""

    std = returns.std(ddof=0)
    if std == 0 or np.isnan(std):
        return 0.0
    return float(returns.mean() / std * np.sqrt(len(returns)))


def sortino_ratio(returns: pd.Series) -> float:
    """Return per-bet Sortino ratio."""

    downside = returns[returns < 0]
    std = downside.std(ddof=0)
    if std == 0 or np.isnan(std):
        return 0.0
    return float(returns.mean() / std * np.sqrt(len(returns)))


def profit_factor(pnl: pd.Series) -> float:
    """Return gross profit divided by gross loss."""

    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def max_drawdown(pnl: pd.Series) -> float:
    """Return max drawdown from cumulative PnL."""

    curve = pnl.cumsum()
    drawdown = curve - curve.cummax()
    return float(drawdown.min())


def calmar_ratio(pnl: pd.Series) -> float:
    """Return total PnL over absolute max drawdown."""

    drawdown = abs(max_drawdown(pnl))
    if drawdown == 0:
        return 0.0
    return float(pnl.sum() / drawdown)


def performance_by_category(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Return PnL and predictive stats by market category."""

    if "category" not in frame.columns:
        return {}
    output: dict[str, dict[str, float]] = {}
    for category, group in frame.groupby("category"):
        output[str(category)] = {
            "bet_count": float(len(group)),
            "net_pnl": float(group["pnl"].sum()),
            "brier_score": brier_score(group["model_probability"], group["outcome"]),
        }
    return output


def edge_decay_profile(frame: pd.DataFrame) -> dict[str, float]:
    """Estimate edge decay using optional delayed model probabilities."""

    output: dict[str, float] = {}
    for column in ["model_probability_1h", "model_probability_6h", "model_probability_24h"]:
        if column in frame.columns:
            horizon = column.removeprefix("model_probability_")
            output[horizon] = float(
                (frame[column].astype(float) - frame["market_probability"].astype(float)).mean()
            )
    return output


def _safe_corr(left: pd.Series, right: pd.Series, *, method: str) -> float:
    value = left.astype(float).corr(right.astype(float), method=method)
    if value is None or np.isnan(value):
        return 0.0
    return float(value)
