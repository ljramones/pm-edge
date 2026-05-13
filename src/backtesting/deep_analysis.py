"""Deep backtest analysis utilities for strategy comparison and diagnostics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtesting.metrics import brier_score, calibration_buckets, performance_by_category


class DeepRunArtifact(BaseModel):
    """In-memory artifact for one deep-backtest run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    metrics: dict[str, float] = Field(default_factory=dict)
    rubric: dict[str, Any] = Field(default_factory=dict)
    signals: pd.DataFrame = Field(default_factory=pd.DataFrame)
    bets: pd.DataFrame = Field(default_factory=pd.DataFrame)
    equity_curve: pd.DataFrame = Field(default_factory=pd.DataFrame)


class DeepAnalysisResult(BaseModel):
    """Structured deep-analysis output tables."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    summary: dict[str, Any] = Field(default_factory=dict)
    ablation: pd.DataFrame = Field(default_factory=pd.DataFrame)
    calibration: pd.DataFrame = Field(default_factory=pd.DataFrame)
    edge_decay: pd.DataFrame = Field(default_factory=pd.DataFrame)
    by_category: pd.DataFrame = Field(default_factory=pd.DataFrame)
    regimes: pd.DataFrame = Field(default_factory=pd.DataFrame)
    confidence_accuracy: pd.DataFrame = Field(default_factory=pd.DataFrame)
    capacity: pd.DataFrame = Field(default_factory=pd.DataFrame)
    failures: pd.DataFrame = Field(default_factory=pd.DataFrame)
    feature_diagnostics: pd.DataFrame = Field(default_factory=pd.DataFrame)
    feature_stability: pd.DataFrame = Field(default_factory=pd.DataFrame)
    rubric_failures: pd.DataFrame = Field(default_factory=pd.DataFrame)
    recommendations: pd.DataFrame = Field(default_factory=pd.DataFrame)
    bootstrap_intervals: pd.DataFrame = Field(default_factory=pd.DataFrame)


def analyze_deep_backtest(runs: Sequence[DeepRunArtifact]) -> DeepAnalysisResult:
    """Build comprehensive diagnostic tables for one or more runs."""

    return DeepAnalysisResult(
        summary=summary_table(runs),
        ablation=feature_contribution_ablation(runs),
        calibration=calibration_analysis(runs),
        edge_decay=edge_decay_curves(runs),
        by_category=performance_by_market_category(runs),
        regimes=regime_analysis(runs),
        confidence_accuracy=confidence_accuracy_correlation(runs),
        capacity=turnover_slippage_capacity_analysis(runs),
        failures=failure_case_studies(runs),
        feature_diagnostics=feature_predictiveness_diagnostics(runs),
        feature_stability=feature_importance_stability(runs),
        rubric_failures=rubric_failure_analysis(runs),
        recommendations=recommendation_matrix(runs),
        bootstrap_intervals=bootstrap_confidence_intervals(runs),
    )


def summary_table(runs: Sequence[DeepRunArtifact]) -> dict[str, Any]:
    """Return compact headline metrics and go/no-go state by run."""

    output: dict[str, Any] = {}
    for run in runs:
        output[run.name] = {
            "rubric_grade": run.rubric.get("grade"),
            "go_no_go": run.rubric.get("go_no_go"),
            "bet_count": run.metrics.get("bet_count", 0.0),
            "net_pnl": run.metrics.get("net_pnl", 0.0),
            "hybrid_net_pnl": run.metrics.get("hybrid_net_pnl"),
            "liquidity_pnl": run.metrics.get("liquidity_pnl"),
            "liquidity_quote_count": run.metrics.get("liquidity_quote_count"),
            "monte_carlo_ruin_probability": run.metrics.get("monte_carlo_ruin_probability"),
            "brier_score": run.metrics.get("brier_score", 0.0),
            "sharpe": run.metrics.get("portfolio_sharpe", run.metrics.get("sharpe", 0.0)),
            "max_drawdown": run.metrics.get(
                "portfolio_max_drawdown", run.metrics.get("max_drawdown", 0.0)
            ),
            "constraints": run.rubric.get("constraints", []),
        }
    return output


def feature_contribution_ablation(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Compare base vs advanced feature runs on key metrics."""

    if not runs:
        return pd.DataFrame()
    baseline = runs[0]
    rows = []
    metric_names = [
        "brier_score",
        "log_loss",
        "net_pnl",
        "return_on_allocated_capital",
        "sharpe",
        "portfolio_sharpe",
        "portfolio_return",
        "profit_factor",
        "max_drawdown",
        "portfolio_max_drawdown",
    ]
    for run in runs:
        for metric in metric_names:
            value = run.metrics.get(metric)
            if value is None:
                continue
            base = baseline.metrics.get(metric, 0.0)
            rows.append(
                {
                    "run": run.name,
                    "metric": metric,
                    "value": value,
                    "baseline_value": base,
                    "delta": value - base,
                    "relative_delta": (value - base) / abs(base) if base else 0.0,
                }
            )
    return pd.DataFrame(rows)


def calibration_analysis(runs: Sequence[DeepRunArtifact], *, bins: int = 10) -> pd.DataFrame:
    """Return reliability bucket stats and Brier by bin."""

    rows = []
    for run in runs:
        frame = _bet_frame(run)
        if frame.empty:
            continue
        for bucket in calibration_buckets(frame, bins=bins):
            rows.append(
                {
                    "run": run.name,
                    **bucket.model_dump(),
                    "brier_bin": bucket.abs_error**2,
                }
            )
    return pd.DataFrame(rows)


def edge_decay_curves(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Estimate edge decay across optional delayed probability columns."""

    rows = []
    for run in runs:
        frame = _bet_frame(run)
        if frame.empty:
            continue
        base_edge = (
            frame["model_probability"].astype(float) - frame["market_probability"].astype(float)
        ).abs()
        for horizon, column in {
            "1h": "model_probability_1h",
            "6h": "model_probability_6h",
            "24h": "model_probability_24h",
        }.items():
            if column in frame:
                delayed_edge = (
                    frame[column].astype(float) - frame["market_probability"].astype(float)
                ).abs()
                decay = 1 - delayed_edge.mean() / max(base_edge.mean(), 1e-9)
            else:
                decay = float("nan")
            rows.append(
                {
                    "run": run.name,
                    "horizon": horizon,
                    "mean_abs_edge": float(base_edge.mean()),
                    "edge_decay": decay,
                }
            )
    return pd.DataFrame(rows)


def performance_by_market_category(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Return predictive and PnL metrics by market category."""

    rows = []
    for run in runs:
        frame = _bet_frame(run)
        by_category = performance_by_category(frame)
        for category, metrics in by_category.items():
            group = frame[frame["category"].astype(str) == str(category)]
            rows.append(
                {
                    "run": run.name,
                    "category": category,
                    **metrics,
                    "hit_rate": _hit_rate(group),
                    "mean_abs_edge": float(group["edge"].astype(float).abs().mean()),
                    "pnl_per_stake": float(
                        group["pnl"].astype(float).sum()
                        / max(group["stake"].astype(float).sum(), 1e-9)
                    ),
                }
            )
    return pd.DataFrame(rows)


def regime_analysis(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Return performance by coarse market regime."""

    rows = []
    for run in runs:
        frame = _bet_frame(run)
        if frame.empty:
            continue
        data = frame.copy()
        data["as_of"] = pd.to_datetime(data["as_of"], utc=True)
        data["quarter"] = data["as_of"].dt.tz_convert(None).dt.to_period("Q").astype(str)
        data["volatility_regime"] = _volatility_regime(data["market_probability"])
        for keys, group in data.groupby(["quarter", "volatility_regime"]):
            quarter, regime = keys
            rows.append(
                {
                    "run": run.name,
                    "quarter": quarter,
                    "regime": regime,
                    "bet_count": float(len(group)),
                    "net_pnl": float(group["pnl"].astype(float).sum()),
                    "brier_score": brier_score(group["model_probability"], group["outcome"]),
                    "hit_rate": _hit_rate(group),
                    "mean_abs_edge": float(group["edge"].astype(float).abs().mean()),
                }
            )
    return pd.DataFrame(rows)


def confidence_accuracy_correlation(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Measure whether confidence and edge magnitude predict realized accuracy."""

    rows = []
    for run in runs:
        frame = _bet_frame(run)
        if frame.empty:
            continue
        data = frame.copy()
        data["correct"] = (
            ((data["edge"].astype(float) > 0) & (data["outcome"].astype(int) == 1))
            | ((data["edge"].astype(float) < 0) & (data["outcome"].astype(int) == 0))
        ).astype(int)
        if "confidence" not in data:
            data["confidence"] = data["edge"].astype(float).abs().clip(0, 1)
        rows.append(
            {
                "run": run.name,
                "confidence_accuracy_corr": _safe_corr(data["confidence"], data["correct"]),
                "edge_abs_accuracy_corr": _safe_corr(
                    data["edge"].astype(float).abs(), data["correct"]
                ),
                "mean_accuracy": float(data["correct"].mean()),
            }
        )
    return pd.DataFrame(rows)


def turnover_slippage_capacity_analysis(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Return turnover, slippage, and coarse capacity diagnostics."""

    rows = []
    for run in runs:
        frame = _bet_frame(run)
        equity = run.equity_curve
        if frame.empty:
            continue
        stake = frame["stake"].astype(float)
        liquidity = (
            frame["liquidity"].astype(float) if "liquidity" in frame else pd.Series(dtype=float)
        )
        capacity = (
            float((liquidity * 0.10).median()) if not liquidity.empty else float(stake.median())
        )
        rows.append(
            {
                "run": run.name,
                "total_turnover": float(stake.sum()),
                "average_stake": float(stake.mean()),
                "average_slippage": float(
                    frame.get("slippage", pd.Series([0.0])).astype(float).mean()
                ),
                "estimated_capacity_10pct_liquidity": capacity,
                "average_portfolio_turnover": (
                    float(equity["turnover"].astype(float).mean())
                    if not equity.empty and "turnover" in equity
                    else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def failure_case_studies(runs: Sequence[DeepRunArtifact], *, top_n: int = 10) -> pd.DataFrame:
    """Return largest losing bets with feature and news context for manual review."""

    rows = []
    for run in runs:
        frame = _bet_frame(run)
        if frame.empty:
            continue
        signals = _signal_frame(run)
        failures = frame.sort_values("pnl").head(top_n)
        for row in failures.to_dict(orient="records"):
            signal_context = _lookup_signal_context(signals, str(row.get("market_id")))
            rows.append(
                {
                    "run": run.name,
                    "market_id": row.get("market_id"),
                    "category": row.get("category"),
                    "as_of": row.get("as_of"),
                    "pnl": row.get("pnl"),
                    "edge": row.get("edge"),
                    "market_probability": row.get("market_probability"),
                    "model_probability": row.get("model_probability"),
                    "outcome": row.get("outcome"),
                    "top_feature_context": signal_context.get("top_feature_context", ""),
                    "news_context": signal_context.get("news_context", ""),
                    "advanced_context": signal_context.get("advanced_context", ""),
                    "hypothesis": _failure_hypothesis(row),
                }
            )
    return pd.DataFrame(rows)


def feature_predictiveness_diagnostics(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Measure which numeric feature columns are predictive versus noisy."""

    rows = []
    for run in runs:
        frame = _joined_signal_outcomes(run)
        if frame.empty:
            continue
        for feature in _feature_columns(frame):
            values = frame[feature].astype(float)
            if values.nunique(dropna=True) < 2:
                continue
            top = frame[values >= values.quantile(0.75)]
            bottom = frame[values <= values.quantile(0.25)]
            rows.append(
                {
                    "run": run.name,
                    "feature": feature,
                    "count": float(values.notna().sum()),
                    "feature_outcome_corr": _safe_corr(values, frame["outcome"]),
                    "feature_edge_corr": _safe_corr(values, frame["edge"].astype(float)),
                    "top_quartile_hit_rate": _hit_rate(top),
                    "bottom_quartile_hit_rate": _hit_rate(bottom),
                    "top_minus_bottom_hit_rate": _hit_rate(top) - _hit_rate(bottom),
                    "top_quartile_pnl": float(
                        top.get("pnl", pd.Series(dtype=float)).astype(float).sum()
                    ),
                    "bottom_quartile_pnl": float(
                        bottom.get("pnl", pd.Series(dtype=float)).astype(float).sum()
                    ),
                    "noise_flag": abs(_safe_corr(values, frame["outcome"])) < 0.03,
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["run", "feature_outcome_corr"], ascending=[True, False])


def feature_importance_stability(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Track feature/outcome correlation stability over calendar quarters."""

    rows = []
    for run in runs:
        frame = _joined_signal_outcomes(run)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["as_of"] = pd.to_datetime(frame["as_of"], utc=True)
        frame["quarter"] = frame["as_of"].dt.tz_convert(None).dt.to_period("Q").astype(str)
        for feature in _feature_columns(frame):
            quarter_corrs: list[float] = []
            for quarter, group in frame.groupby("quarter"):
                if len(group) < 3 or group[feature].astype(float).nunique(dropna=True) < 2:
                    continue
                corr = _safe_corr(group[feature].astype(float), group["outcome"])
                quarter_corrs.append(corr)
                rows.append(
                    {
                        "run": run.name,
                        "feature": feature,
                        "quarter": quarter,
                        "quarter_corr": corr,
                        "quarter_count": float(len(group)),
                        "stability_score": float("nan"),
                        "sign_flip_rate": float("nan"),
                    }
                )
            if quarter_corrs:
                signs = [1 if value > 0 else -1 if value < 0 else 0 for value in quarter_corrs]
                majority = max(set(signs), key=signs.count)
                sign_flip_rate = sum(1 for sign in signs if sign not in {0, majority}) / len(signs)
                stability = 1.0 / (1.0 + float(np.std(quarter_corrs)))
                rows.append(
                    {
                        "run": run.name,
                        "feature": feature,
                        "quarter": "all",
                        "quarter_corr": float(np.mean(quarter_corrs)),
                        "quarter_count": float(len(frame)),
                        "stability_score": stability,
                        "sign_flip_rate": sign_flip_rate,
                    }
                )
    return pd.DataFrame(rows)


def rubric_failure_analysis(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Explain whether failure is sample size, overfit risk, weak signal, or risk constraint."""

    rows = []
    for run in runs:
        metrics = run.metrics
        constraints = run.rubric.get("constraints", [])
        bet_count = float(metrics.get("bet_count", 0.0))
        brier = float(metrics.get("brier_score", 1.0))
        pnl = float(metrics.get("net_pnl", 0.0))
        max_drawdown = _drawdown_ratio(metrics)
        if bet_count < 100:
            primary = "sample_size"
        elif brier >= 0.22 and pnl <= 0:
            primary = "weak_signal"
        elif brier >= 0.22 and pnl > 0:
            primary = "miscalibration"
        elif max_drawdown > 0.20:
            primary = "risk"
        else:
            primary = "statistical_significance"
        rows.append(
            {
                "run": run.name,
                "grade": run.rubric.get("grade"),
                "go_no_go": run.rubric.get("go_no_go"),
                "primary_failure_mode": primary,
                "bet_count": bet_count,
                "brier_score": brier,
                "net_pnl": pnl,
                "max_drawdown": max_drawdown,
                "constraints": "; ".join(str(item) for item in constraints),
                "rubric_recommendation": rubric_recommendation(primary, metrics),
            }
        )
    return pd.DataFrame(rows)


def recommendation_matrix(runs: Sequence[DeepRunArtifact]) -> pd.DataFrame:
    """Return concrete A/B/C recommendations from the diagnostic tables."""

    category = performance_by_market_category(runs)
    failures = rubric_failure_analysis(runs)
    feature_diag = feature_predictiveness_diagnostics(runs)
    rows = []
    for run in runs:
        run_categories = (
            category[category["run"] == run.name] if not category.empty else pd.DataFrame()
        )
        run_failures = (
            failures[failures["run"] == run.name] if not failures.empty else pd.DataFrame()
        )
        run_features = (
            feature_diag[feature_diag["run"] == run.name]
            if not feature_diag.empty
            else pd.DataFrame()
        )
        best_category = _best_category(run_categories)
        positive_categories = (
            int((run_categories["net_pnl"].astype(float) > 0).sum())
            if not run_categories.empty and "net_pnl" in run_categories
            else 0
        )
        primary_failure = (
            str(run_failures["primary_failure_mode"].iloc[0])
            if not run_failures.empty
            else "unknown"
        )
        stable_predictors = 0
        if not run_features.empty and "noise_flag" in run_features:
            stable_predictors = int((~run_features["noise_flag"].astype(bool)).sum())
        recommendation = choose_project_recommendation(
            run=run,
            positive_categories=positive_categories,
            stable_predictors=stable_predictors,
            primary_failure=primary_failure,
        )
        rows.append(
            {
                "run": run.name,
                "recommendation": recommendation,
                "best_category": best_category,
                "positive_categories": positive_categories,
                "stable_predictive_features": stable_predictors,
                "primary_failure_mode": primary_failure,
                "next_experiments": next_experiments(
                    recommendation=recommendation,
                    best_category=best_category,
                    primary_failure=primary_failure,
                ),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_confidence_intervals(
    runs: Sequence[DeepRunArtifact], *, samples: int = 500, seed: int = 7
) -> pd.DataFrame:
    """Bootstrap confidence intervals for PnL, hit rate, and Brier score."""

    rng = np.random.default_rng(seed)
    rows = []
    for run in runs:
        frame = _bet_frame(run)
        if frame.empty:
            continue
        values: dict[str, list[float]] = {"net_pnl": [], "hit_rate": [], "brier_score": []}
        for _ in range(samples):
            sample = frame.iloc[rng.integers(0, len(frame), size=len(frame))]
            values["net_pnl"].append(float(sample["pnl"].astype(float).sum()))
            values["hit_rate"].append(_hit_rate(sample))
            values["brier_score"].append(
                brier_score(sample["model_probability"], sample["outcome"])
            )
        for metric, metric_values in values.items():
            rows.append(
                {
                    "run": run.name,
                    "metric": metric,
                    "mean": float(np.mean(metric_values)),
                    "ci_lower": float(np.quantile(metric_values, 0.025)),
                    "ci_upper": float(np.quantile(metric_values, 0.975)),
                    "sample_count": float(len(frame)),
                    "bootstrap_samples": float(samples),
                }
            )
    return pd.DataFrame(rows)


def flatten_feature_column(frame: pd.DataFrame) -> pd.DataFrame:
    """Expand a `features` dict column into top-level numeric columns."""

    if "features" not in frame:
        return frame
    records = []
    for value in frame["features"]:
        if isinstance(value, Mapping):
            records.append(dict(value))
        else:
            records.append({})
    feature_frame = pd.json_normalize(records)
    base_frame = frame.drop(columns=["features"]).reset_index(drop=True)
    if feature_frame.empty:
        return base_frame
    duplicate_columns = [column for column in feature_frame.columns if column in base_frame.columns]
    feature_frame = feature_frame.drop(columns=duplicate_columns).reset_index(drop=True)
    if feature_frame.empty:
        return base_frame
    return pd.concat([base_frame, feature_frame], axis=1)


def rubric_recommendation(primary_failure: str, metrics: Mapping[str, float]) -> str:
    """Return whether to keep or relax rubric constraints."""

    if primary_failure == "sample_size" and float(metrics.get("net_pnl", 0.0)) > 0:
        return "Keep strict Go/No-Go; add a Research-Promising label for positive small samples."
    if primary_failure == "miscalibration":
        return "Keep Brier/calibration strict; improve calibration before relaxing any constraint."
    if primary_failure == "weak_signal":
        return "Keep rubric strict; weak predictive value should not be allowed through."
    if primary_failure == "risk":
        return "Keep risk constraints strict; reduce exposure or position sizing."
    return "Keep strict until significance clears on fresh holdout."


def choose_project_recommendation(
    *,
    run: DeepRunArtifact,
    positive_categories: int,
    stable_predictors: int,
    primary_failure: str,
) -> str:
    """Choose A/B/C project recommendation."""

    pnl = float(run.metrics.get("net_pnl", 0.0))
    brier = float(run.metrics.get("brier_score", 1.0))
    if (
        pnl > 0
        and positive_categories >= 2
        and primary_failure in {"sample_size", "miscalibration"}
    ):
        return "A. Continue iterating"
    if pnl > 0 and positive_categories == 1:
        return "B. Pivot to narrower domain"
    if pnl > 0 and stable_predictors >= 2 and brier < 0.24:
        return "A. Continue iterating"
    return "C. Pause / wind down"


def next_experiments(*, recommendation: str, best_category: str, primary_failure: str) -> str:
    """Return concrete next experiments for the recommendation."""

    if recommendation.startswith("A"):
        if primary_failure == "sample_size":
            return (
                "Expand resolved-market sample; rerun base/advanced ablation; add bootstrap confidence intervals; "
                f"test stricter thresholds in {best_category}."
            )
        return (
            "Recalibrate probabilities with isotonic/Platt by category; drop noisy features; "
            f"run category-specific threshold search for {best_category}."
        )
    if recommendation.startswith("B"):
        return f"Restrict to {best_category}; build domain-specific feature set; retest capacity and slippage only inside that domain."
    return "Stop adding features; collect more resolved data or switch to a clearer edge source before further modeling."


def _bet_frame(run: DeepRunArtifact) -> pd.DataFrame:
    frame = run.bets.copy()
    if frame.empty:
        return frame
    for column in ["model_probability", "market_probability", "outcome", "pnl", "stake", "edge"]:
        if column in frame:
            frame[column] = frame[column].astype(float)
    return frame


def _signal_frame(run: DeepRunArtifact) -> pd.DataFrame:
    frame = flatten_feature_column(run.signals.copy())
    if frame.empty:
        return frame
    if "market_id" in frame:
        frame["market_id"] = frame["market_id"].astype(str)
    return frame


def _joined_signal_outcomes(run: DeepRunArtifact) -> pd.DataFrame:
    bets = _bet_frame(run)
    signals = _signal_frame(run)
    if bets.empty:
        return pd.DataFrame()
    if signals.empty:
        return bets
    signal_columns = [
        column
        for column in signals.columns
        if column not in bets.columns or column in {"market_id", "as_of"}
    ]
    return bets.merge(
        signals[signal_columns],
        on=["market_id", "as_of"],
        how="left",
        suffixes=("", "_signal"),
    )


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {
        "market_id",
        "as_of",
        "resolved_at",
        "venue",
        "category",
        "outcome",
        "pnl",
        "stake",
        "fee",
        "slippage",
        "return_on_capital",
        "entry_price",
        "edge",
        "market_probability",
        "model_probability",
        "base_model_probability",
        "advanced_model_probability",
    }
    candidates = []
    for column in frame.columns:
        if column in excluded:
            continue
        if pd.api.types.is_numeric_dtype(frame[column]):
            candidates.append(column)
    return candidates


def _lookup_signal_context(signals: pd.DataFrame, market_id: str) -> dict[str, str]:
    if signals.empty or "market_id" not in signals:
        return {}
    matches = signals[signals["market_id"].astype(str) == market_id]
    if matches.empty:
        return {}
    row = matches.iloc[-1].to_dict()
    numeric = {
        key: float(value)
        for key, value in row.items()
        if isinstance(value, int | float | np.number)
        and not isinstance(value, bool)
        and key not in {"outcome"}
    }
    top_features = sorted(numeric.items(), key=lambda item: abs(item[1]), reverse=True)[:8]
    news_bits = [
        str(value)
        for key in ["news_context", "llm_reasoning", "reasoning"]
        if _is_report_scalar(value := row.get(key))
    ]
    advanced = {
        key: row.get(key)
        for key in row
        if key.startswith(("llm_", "onchain_", "news_velocity_", "cross_source_"))
        and _is_report_scalar(row.get(key))
    }
    return {
        "top_feature_context": "; ".join(f"{key}={value:.4f}" for key, value in top_features),
        "news_context": " | ".join(news_bits)[:500],
        "advanced_context": "; ".join(f"{key}={value}" for key, value in advanced.items())[:500],
    }


def _is_report_scalar(value: Any) -> bool:
    """Return whether a value can be safely rendered in compact report context."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool | int | float | np.number):
        return not pd.isna(value)
    return False


def _hit_rate(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    correct = ((frame["edge"].astype(float) > 0) & (frame["outcome"].astype(int) == 1)) | (
        (frame["edge"].astype(float) < 0) & (frame["outcome"].astype(int) == 0)
    )
    return float(correct.mean())


def _best_category(frame: pd.DataFrame) -> str:
    if frame.empty or "net_pnl" not in frame:
        return "unknown"
    best = frame.sort_values("net_pnl", ascending=False).iloc[0]
    return str(best.get("category", "unknown"))


def _drawdown_ratio(metrics: Mapping[str, float]) -> float:
    if "portfolio_max_drawdown_pct" in metrics:
        return abs(float(metrics["portfolio_max_drawdown_pct"]))
    raw = abs(float(metrics.get("portfolio_max_drawdown", metrics.get("max_drawdown", 0.0))))
    return raw if raw <= 1 else 0.0


def _volatility_regime(probabilities: pd.Series) -> pd.Series:
    rolling = probabilities.astype(float).rolling(10, min_periods=1).std().fillna(0.0)
    threshold = rolling.quantile(0.75)
    return pd.Series(
        np.where(rolling >= threshold, "high_volatility", "normal"), index=probabilities.index
    )


def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    if left.astype(float).nunique(dropna=True) < 2 or right.astype(float).nunique(dropna=True) < 2:
        return 0.0
    value = left.astype(float).corr(right.astype(float))
    if value is None or math.isnan(value):
        return 0.0
    return float(value)


def _failure_hypothesis(row: Mapping[str, Any]) -> str:
    edge = abs(float(row.get("edge", 0.0) or 0.0))
    slippage = float(row.get("slippage", 0.0) or 0.0)
    if edge >= 0.08:
        return "Large-edge miss; inspect source quality, stale information, and resolution rules."
    if slippage > 0.01:
        return "Execution cost appears material; test lower capacity or stricter liquidity filters."
    return "Routine loser; check calibration bucket and category-level hit rate."
