"""Pre-registered backtest evaluation rubric."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RubricDecision(BaseModel):
    """Decision grade plus reasons."""

    model_config = ConfigDict(frozen=True)

    grade: str
    reasons: list[str] = Field(default_factory=list)
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
        ]
        if decision_grade:
            return RubricDecision(grade="Decision-Grade", reasons=reasons)
        if promising:
            return RubricDecision(grade="Promising", reasons=reasons)
        return RubricDecision(grade="Fail", reasons=reasons)
