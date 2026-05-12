"""Live paper performance tracking and degradation checks."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.models import utc_now
from strategies import EdgeSignal


class LiveRubricDecision(BaseModel):
    """Decision grade plus reasons for live paper monitoring."""

    model_config = ConfigDict(frozen=True)

    grade: str
    reasons: list[str] = Field(default_factory=list)


class LiveEvaluationRubric:
    """Lightweight Decision-Grade / Promising / Fail rubric for live paper snapshots."""

    def evaluate(self, metrics: dict[str, float]) -> LiveRubricDecision:
        """Evaluate live metrics against conservative monitoring thresholds."""

        mean_edge = metrics.get("mean_edge", 0.0)
        brier = metrics.get("brier_score", 1.0)
        net_pnl = metrics.get("net_pnl", 0.0)
        bet_count = metrics.get("bet_count", 0.0)
        reasons = [
            f"mean_edge={mean_edge:.4f}",
            f"brier_score={brier:.4f}",
            f"net_pnl={net_pnl:.4f}",
            f"bet_count={bet_count:.0f}",
        ]
        if abs(mean_edge) >= 0.04 and brier < 0.18 and net_pnl > 0 and bet_count >= 50:
            return LiveRubricDecision(grade="Decision-Grade", reasons=reasons)
        if abs(mean_edge) >= 0.02 and brier < 0.22 and bet_count >= 10:
            return LiveRubricDecision(grade="Promising", reasons=reasons)
        return LiveRubricDecision(grade="Fail", reasons=reasons)


class LivePerformanceSnapshot(BaseModel):
    """Aggregate live-paper metrics at one timestamp."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime = Field(default_factory=utc_now)
    equity: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    mean_edge: float = 0.0
    signal_count: int = 0
    brier_score: float | None = None
    calibration_drift: float = 0.0
    edge_decay: float = 0.0
    degradation_flags: list[str] = Field(default_factory=list)
    rubric: LiveRubricDecision


class PerformanceTracker:
    """Track live signal quality and compare it to a fixed rubric."""

    def __init__(
        self,
        *,
        baseline_brier_score: float = 0.22,
        calibration_drift_threshold: float = 0.10,
        edge_decay_threshold: float = 0.50,
        rubric: LiveEvaluationRubric | None = None,
    ) -> None:
        self.baseline_brier_score = baseline_brier_score
        self.calibration_drift_threshold = calibration_drift_threshold
        self.edge_decay_threshold = edge_decay_threshold
        self.rubric = rubric or LiveEvaluationRubric()
        self.snapshots: list[LivePerformanceSnapshot] = []

    def record(
        self,
        *,
        signals: Sequence[EdgeSignal],
        equity: float,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0,
        outcomes: dict[str, int] | None = None,
        as_of: datetime | None = None,
    ) -> LivePerformanceSnapshot:
        """Record one live monitoring snapshot."""

        mean_edge = _mean([abs(signal.edge) for signal in signals])
        brier = self._brier(signals, outcomes or {})
        calibration_drift = _mean(
            [abs(signal.model_prob - signal.market_prob) for signal in signals]
        )
        edge_decay = self._edge_decay(mean_edge)
        flags = self._degradation_flags(
            brier_score=brier,
            calibration_drift=calibration_drift,
            edge_decay=edge_decay,
        )
        metrics = {
            "mean_edge": mean_edge,
            "brier_score": brier if brier is not None else self.baseline_brier_score,
            "sharpe": 0.0,
            "net_pnl": realized_pnl + unrealized_pnl,
            "profit_factor": 0.0,
            "bet_count": float(len(signals)),
            "portfolio_sharpe": 0.0,
            "portfolio_calmar": 0.0,
            "max_exposure": 0.0,
        }
        snapshot = LivePerformanceSnapshot(
            as_of=as_of or utc_now(),
            equity=equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            mean_edge=mean_edge,
            signal_count=len(signals),
            brier_score=brier,
            calibration_drift=calibration_drift,
            edge_decay=edge_decay,
            degradation_flags=flags,
            rubric=self.rubric.evaluate(metrics),
        )
        self.snapshots.append(snapshot)
        return snapshot

    def daily_summary(self) -> dict[str, float | str]:
        """Return a compact summary over recorded live snapshots."""

        if not self.snapshots:
            return {"snapshot_count": 0.0, "rubric_grade": "Fail"}
        latest = self.snapshots[-1]
        return {
            "snapshot_count": float(len(self.snapshots)),
            "latest_equity": latest.equity,
            "latest_mean_edge": latest.mean_edge,
            "latest_signal_count": float(latest.signal_count),
            "rubric_grade": latest.rubric.grade,
        }

    def _brier(self, signals: Sequence[EdgeSignal], outcomes: dict[str, int]) -> float | None:
        scored = [
            (signal.model_prob - outcomes[signal.market_id]) ** 2
            for signal in signals
            if signal.market_id in outcomes
        ]
        return _mean(scored) if scored else None

    def _edge_decay(self, current_mean_edge: float) -> float:
        if len(self.snapshots) < 3:
            return 0.0
        prior = _mean([snapshot.mean_edge for snapshot in self.snapshots[-3:]])
        if prior <= 0:
            return 0.0
        return max(0.0, (prior - current_mean_edge) / prior)

    def _degradation_flags(
        self,
        *,
        brier_score: float | None,
        calibration_drift: float,
        edge_decay: float,
    ) -> list[str]:
        flags: list[str] = []
        if brier_score is not None and brier_score > self.baseline_brier_score:
            flags.append("brier_worse_than_baseline")
        if calibration_drift > self.calibration_drift_threshold:
            flags.append("calibration_drift")
        if edge_decay > self.edge_decay_threshold:
            flags.append("edge_decay")
        return flags


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
