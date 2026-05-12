"""Edge signal generation from Phase 1 features and probability models."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from core.client import UnifiedMarket
from features.feature_store import FeatureStore, FeatureVector
from models.baselines import ProbabilityModel
from utils.logging import get_logger

logger = get_logger(__name__)


class EdgeSignal(BaseModel):
    """Model-vs-market edge signal for one market."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    market_prob: float
    model_prob: float
    edge: float
    confidence: float
    reasoning: list[str] = Field(default_factory=list)
    features: dict[str, float] = Field(default_factory=dict)


class EdgeDetector:
    """Build features, run probability models, and return edge signals."""

    def __init__(
        self,
        feature_store: FeatureStore,
        models: list[ProbabilityModel] | None = None,
        *,
        use_advanced_features: bool = False,
    ) -> None:
        self.feature_store = feature_store
        self.models = models or []
        self.use_advanced_features = use_advanced_features

    async def score_market(
        self,
        market: UnifiedMarket,
        *,
        market_probability: float | None = None,
        model_context: dict[str, Any] | None = None,
    ) -> EdgeSignal:
        """Score one market and return a probability edge signal."""

        context = model_context or {}
        vector = await self.feature_store.build_market_features(market, **context)
        inferred_market_prob = market_probability or vector.market_probability or Decimal("0.5")
        market_prob = float(inferred_market_prob)
        model_prob = self._model_probability(vector)
        advanced_adjustment = (
            self._advanced_probability_adjustment(vector) if self.use_advanced_features else 0.0
        )
        if advanced_adjustment:
            model_prob = float(np.clip(model_prob + advanced_adjustment, 0.01, 0.99))
        edge = model_prob - market_prob
        confidence = self._confidence(vector, edge)
        reasoning = self._reasoning(vector, market_prob, model_prob)
        logger.info(
            "edge_signal_generated",
            market_id=market.market_id,
            market_prob=market_prob,
            model_prob=model_prob,
            edge=edge,
            confidence=confidence,
            advanced_adjustment=advanced_adjustment,
        )
        return EdgeSignal(
            market_id=market.market_id,
            market_prob=market_prob,
            model_prob=model_prob,
            edge=edge,
            confidence=confidence,
            reasoning=reasoning,
            features=vector.features,
        )

    async def rank_markets(
        self,
        markets: list[UnifiedMarket],
        *,
        contexts: dict[str, dict[str, Any]] | None = None,
    ) -> list[EdgeSignal]:
        """Return markets ranked by absolute edge."""

        signals = [
            await self.score_market(
                market, model_context=(contexts or {}).get(market.market_id, {})
            )
            for market in markets
        ]
        return sorted(
            signals, key=lambda signal: abs(signal.edge) * signal.confidence, reverse=True
        )

    def _model_probability(self, vector: FeatureVector) -> float:
        frame = vector.to_frame().drop(columns=["market_id", "as_of"])
        if self.models:
            probabilities = [model.predict_proba(frame)[0] for model in self.models]
            return float(np.clip(np.mean(probabilities), 0.01, 0.99))

        # Cold-start heuristic: combine strongest available public signal before training.
        poll = vector.features.get("poll_top_probability", 0.5)
        sentiment = vector.features.get("sentiment_24h", 0.0)
        conditional = vector.features.get("implied_conditional_probability", 0.5)
        divergence = vector.features.get("price_divergence", 0.0)
        probability = (
            0.55 * poll
            + 0.30 * conditional
            + 0.10 * (0.5 + sentiment / 2)
            + 0.05 * (0.5 + divergence)
        )
        return float(np.clip(probability, 0.01, 0.99))

    def _advanced_probability_adjustment(self, vector: FeatureVector) -> float:
        llm_probability = vector.features.get("llm_probability")
        llm_score = vector.features.get("llm_news_score", 0.0)
        llm_momentum = vector.features.get("llm_news_momentum", 0.0)
        onchain = (
            vector.features.get("onchain_tvl_change_24h", 0.0)
            + 0.20 * vector.features.get("onchain_volume_surge", 0.0)
            + 0.05 * vector.features.get("onchain_whale_activity", 0.0)
        )
        uncertainty = vector.features.get("llm_uncertainty", 0.5)
        agreement = vector.features.get("cross_source_agreement", 0.0)
        fear_multiplier = vector.features.get("fear_sizing_multiplier", 1.0)
        if llm_probability is None:
            return 0.0
        raw = (
            0.08 * (llm_probability - 0.5) + 0.04 * llm_score + 0.03 * llm_momentum + 0.03 * onchain
        )
        confidence_multiplier = max(0.25, 1.0 - uncertainty) * (0.75 + 0.25 * agreement)
        adjustment = raw * confidence_multiplier * max(0.25, min(1.25, fear_multiplier))
        logger.info(
            "advanced_feature_contribution",
            market_id=vector.market_id,
            llm_probability=llm_probability,
            llm_score=llm_score,
            llm_momentum=llm_momentum,
            onchain_score=onchain,
            uncertainty=uncertainty,
            agreement=agreement,
            adjustment=adjustment,
        )
        return float(np.clip(adjustment, -0.08, 0.08))

    def _confidence(self, vector: FeatureVector, edge: float) -> float:
        poll_count = min(vector.features.get("poll_count", 0.0) / 10, 1.0)
        mentions = min(vector.features.get("mention_count_7d", 0.0) / 50, 1.0)
        liquidity = min(vector.features.get("top_book_liquidity", 0.0) / 1000, 1.0)
        magnitude = min(abs(edge) / 0.10, 1.0)
        agreement = min(vector.features.get("cross_source_agreement", 0.0), 1.0)
        return float(
            np.clip(
                0.22 * poll_count
                + 0.18 * mentions
                + 0.22 * liquidity
                + 0.28 * magnitude
                + 0.10 * agreement,
                0.0,
                1.0,
            )
        )

    def _reasoning(self, vector: FeatureVector, market_prob: float, model_prob: float) -> list[str]:
        reasons = [
            f"model probability {model_prob:.3f} vs market {market_prob:.3f}",
            f"poll top probability {vector.features.get('poll_top_probability', 0.5):.3f}",
            f"sentiment 24h {vector.features.get('sentiment_24h', 0.0):.3f}",
            f"cross-market conditional {vector.features.get('implied_conditional_probability', 0.5):.3f}",
        ]
        if vector.features.get("spread", 0.0) > 0:
            reasons.append(f"spread {vector.features['spread']:.3f}")
        if self.use_advanced_features and "llm_probability" in vector.features:
            reasons.append(
                "advanced llm probability "
                f"{vector.features.get('llm_probability', 0.5):.3f}, "
                f"uncertainty {vector.features.get('llm_uncertainty', 0.5):.3f}"
            )
        if self.use_advanced_features and vector.features.get("onchain_tvl_change_24h", 0.0):
            reasons.append(
                f"on-chain tvl change {vector.features.get('onchain_tvl_change_24h', 0.0):.3f}"
            )
        return reasons
