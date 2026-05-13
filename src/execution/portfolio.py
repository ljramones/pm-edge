"""Portfolio construction with fractional Kelly sizing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict

from strategies import EdgeSignal


class TargetPosition(BaseModel):
    """Desired portfolio target for one edge signal."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    direction: int
    target_weight: float
    target_notional: float
    market_prob: float
    model_prob: float
    edge: float
    confidence: float


@dataclass(frozen=True)
class KellyPortfolioConfig:
    """Portfolio-level risk controls."""

    kelly_fraction: float = 0.4
    max_position_weight: float = 0.05
    max_total_exposure: float = 0.2
    min_edge: float = 0.02
    min_confidence: float = 0.05
    liquidity_fraction_cap: float = 0.1
    correlation_penalty: float = 0.5
    quarter_kelly: bool = False
    min_cash_buffer: float = 0.0
    min_post_cost_edge: float = 0.0
    impact_coefficient: float = 0.10
    max_cluster_exposure: float = 0.12
    ignore_liquidity_cap: bool = False


class KellyFractionalPortfolio:
    """Convert edge signals into bounded fractional-Kelly target positions."""

    def __init__(self, config: KellyPortfolioConfig | None = None) -> None:
        self.config = config or KellyPortfolioConfig()

    def allocate(
        self,
        signals: list[EdgeSignal],
        *,
        capital: float,
        liquidity: dict[str, float] | None = None,
        correlations: dict[tuple[str, str], float] | None = None,
    ) -> list[TargetPosition]:
        """Return target positions respecting edge, confidence, exposure, and correlation limits."""

        candidates: list[TargetPosition] = []
        for signal in signals:
            edge_for_gate = (
                self._post_cost_edge(signal)
                if self.config.min_post_cost_edge > 0
                else abs(signal.edge)
            )
            edge_threshold = max(self.config.min_edge, self.config.min_post_cost_edge)
            if edge_for_gate < edge_threshold or signal.confidence < self.config.min_confidence:
                continue

            direction = 1 if signal.edge > 0 else -1
            raw_weight = self._kelly_weight(signal, direction=direction)
            penalized_weight = raw_weight * self._correlation_multiplier(
                signal.market_id, signals, correlations
            )
            capped_weight = min(penalized_weight, self.config.max_position_weight)
            if not self.config.ignore_liquidity_cap and liquidity and signal.market_id in liquidity:
                capped_weight = min(
                    capped_weight,
                    liquidity[signal.market_id]
                    * self.config.liquidity_fraction_cap
                    / max(capital, 1e-9),
                )
            if capped_weight <= 0:
                continue

            candidates.append(
                TargetPosition(
                    market_id=signal.market_id,
                    direction=direction,
                    target_weight=capped_weight,
                    target_notional=capped_weight * capital,
                    market_prob=signal.market_prob,
                    model_prob=signal.model_prob,
                    edge=signal.edge,
                    confidence=signal.confidence,
                )
            )

        total_weight = sum(position.target_weight for position in candidates)
        exposure_cap = min(self.config.max_total_exposure, 1.0 - self.config.min_cash_buffer)
        if total_weight <= exposure_cap:
            return sorted(
                candidates, key=lambda item: abs(item.edge) * item.confidence, reverse=True
            )

        scale = exposure_cap / total_weight
        return sorted(
            [
                position.model_copy(
                    update={
                        "target_weight": position.target_weight * scale,
                        "target_notional": position.target_notional * scale,
                    }
                )
                for position in candidates
            ],
            key=lambda item: abs(item.edge) * item.confidence,
            reverse=True,
        )

    def _kelly_weight(self, signal: EdgeSignal, *, direction: int) -> float:
        market_prob = np.clip(signal.market_prob, 0.001, 0.999)
        model_prob = np.clip(signal.model_prob, 0.001, 0.999)
        if direction > 0:
            full_kelly = (model_prob - market_prob) / max(1 - market_prob, 1e-9)
        else:
            full_kelly = (market_prob - model_prob) / max(market_prob, 1e-9)
        kelly_fraction = 0.25 if self.config.quarter_kelly else self.config.kelly_fraction
        return float(max(0.0, full_kelly * kelly_fraction * signal.confidence))

    def _post_cost_edge(self, signal: EdgeSignal) -> float:
        liquidity = max(float(signal.features.get("top_book_liquidity", 0.0)), 1.0)
        impact = self.config.impact_coefficient / (liquidity**0.5)
        return float(max(0.0, abs(signal.edge) - impact))

    def _correlation_multiplier(
        self,
        market_id: str,
        signals: list[EdgeSignal],
        correlations: dict[tuple[str, str], float] | None,
    ) -> float:
        if not correlations:
            return 1.0
        related = [
            abs(correlation)
            for other in signals
            if other.market_id != market_id
            for correlation in [
                correlations.get((market_id, other.market_id))
                or correlations.get((other.market_id, market_id))
            ]
            if correlation is not None
        ]
        if not related:
            return 1.0
        avg_corr = sum(related) / len(related)
        return max(0.0, 1 - self.config.correlation_penalty * avg_corr)
