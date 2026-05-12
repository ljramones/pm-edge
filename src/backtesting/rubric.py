"""Pre-registered backtest evaluation rubric."""

from __future__ import annotations

from math import erfc, sqrt

from pydantic import BaseModel, ConfigDict, Field


class RubricDecision(BaseModel):
    """Decision grade plus reasons."""

    model_config = ConfigDict(frozen=True)

    grade: str
    reasons: list[str] = Field(default_factory=list)
    go_no_go: str = "No-Go"
    significance: dict[str, float] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    multiple_testing_note: str = (
        "Treat this as pre-registered only for the stated strategy/version. "
        "New feature searches or threshold tuning require a fresh holdout or multiple-testing adjustment."
    )


class EvaluationRubric:
    """Decision-Grade / Promising / Fail rubric for signal readiness."""

    def evaluate(self, metrics: dict[str, float]) -> RubricDecision:
        """Evaluate metrics against fixed thresholds."""

        mean_edge = metrics.get("mean_edge", 0.0)
        brier = metrics.get("brier_score", 1.0)
        sharpe = metrics.get("sharpe", 0.0)
        net_pnl = metrics.get("net_pnl", 0.0)
        profit_factor = metrics.get("profit_factor", 0.0)
        bet_count = metrics.get("bet_count", 0.0)
        portfolio_sharpe = metrics.get("portfolio_sharpe", sharpe)
        portfolio_calmar = metrics.get("portfolio_calmar", metrics.get("calmar", 0.0))
        max_exposure = metrics.get("max_exposure", 0.0)
        max_drawdown = drawdown_ratio(metrics)
        hit_rate_4pct = metrics.get("hit_rate_edge_ge_4%", 0.0)
        hit_count = metrics.get("hit_count_edge_ge_4%", bet_count)
        hit_rate_p_value = binomial_p_value(hit_rate_4pct, hit_count)
        pnl_t_stat = metrics.get("pnl_t_stat", 0.0)
        pnl_p_value = two_sided_normal_p_value(pnl_t_stat)

        decision_grade = (
            abs(mean_edge) >= 0.04
            and brier < 0.18
            and max(sharpe, portfolio_sharpe) > 1.2
            and net_pnl > 0
            and profit_factor > 1.3
            and bet_count >= 50
            and (max_exposure == 0.0 or max_exposure <= 0.35)
        )
        promising = (
            abs(mean_edge) >= 0.02
            and brier < 0.22
            and max(sharpe, portfolio_sharpe) > 0.5
            and net_pnl > 0
            and bet_count >= 25
        )

        reasons = [
            f"mean_edge={mean_edge:.4f}",
            f"brier_score={brier:.4f}",
            f"sharpe={sharpe:.4f}",
            f"net_pnl={net_pnl:.4f}",
            f"profit_factor={profit_factor:.4f}",
            f"bet_count={bet_count:.0f}",
            f"portfolio_sharpe={portfolio_sharpe:.4f}",
            f"portfolio_calmar={portfolio_calmar:.4f}",
            f"max_exposure={max_exposure:.4f}",
            f"max_drawdown={max_drawdown:.4f}",
            f"hit_rate_edge_ge_4%={hit_rate_4pct:.4f}",
            f"hit_rate_p_value={hit_rate_p_value:.4f}",
            f"pnl_t_stat={pnl_t_stat:.4f}",
            f"pnl_p_value={pnl_p_value:.4f}",
        ]
        constraints = go_no_go_constraints(
            decision_grade=decision_grade,
            hit_rate_p_value=hit_rate_p_value,
            pnl_p_value=pnl_p_value,
            max_drawdown=max_drawdown,
            max_exposure=max_exposure,
            bet_count=bet_count,
        )
        significance = {
            "hit_rate_p_value": hit_rate_p_value,
            "pnl_p_value": pnl_p_value,
            "pnl_t_stat": pnl_t_stat,
        }
        go_no_go = "Go" if decision_grade and not constraints else "No-Go"
        if decision_grade:
            return RubricDecision(
                grade="Decision-Grade",
                reasons=reasons,
                go_no_go=go_no_go,
                significance=significance,
                constraints=constraints,
            )
        if promising:
            return RubricDecision(
                grade="Promising",
                reasons=reasons,
                go_no_go="No-Go",
                significance=significance,
                constraints=constraints or ["Promising is not sufficient for real-money launch."],
            )
        return RubricDecision(
            grade="Fail",
            reasons=reasons,
            go_no_go="No-Go",
            significance=significance,
            constraints=constraints or ["Rubric failed minimum predictive/economic thresholds."],
        )


def binomial_p_value(hit_rate: float, count: float, *, null_rate: float = 0.5) -> float:
    """Approximate two-sided binomial p-value with normal approximation."""

    if count <= 0:
        return 1.0
    std = sqrt(null_rate * (1 - null_rate) / count)
    if std <= 0:
        return 1.0
    z_score = abs(hit_rate - null_rate) / std
    return two_sided_normal_p_value(z_score)


def two_sided_normal_p_value(z_score: float) -> float:
    """Return a two-sided p-value from a normal z-score approximation."""

    return float(erfc(abs(z_score) / sqrt(2)))


def go_no_go_constraints(
    *,
    decision_grade: bool,
    hit_rate_p_value: float,
    pnl_p_value: float,
    max_drawdown: float,
    max_exposure: float,
    bet_count: float,
) -> list[str]:
    """Return blockers for moving from paper research to real-money review."""

    constraints: list[str] = []
    if not decision_grade:
        constraints.append("Strategy is not Decision-Grade.")
    if bet_count < 100:
        constraints.append("Fewer than 100 qualifying bets; sample is too small.")
    if hit_rate_p_value > 0.05 and pnl_p_value > 0.05:
        constraints.append("Neither hit-rate nor PnL significance clears p <= 0.05.")
    if max_drawdown > 0.20:
        constraints.append("Drawdown exceeds 20% capital-risk tolerance.")
    if max_exposure > 0.35:
        constraints.append("Portfolio exposure exceeds 35% cap.")
    return constraints


def drawdown_ratio(metrics: dict[str, float]) -> float:
    """Return drawdown as a capital ratio when available."""

    if "portfolio_max_drawdown_pct" in metrics:
        return abs(metrics["portfolio_max_drawdown_pct"])
    raw = abs(metrics.get("portfolio_max_drawdown", metrics.get("max_drawdown", 0.0)))
    return raw if raw <= 1 else 0.0
