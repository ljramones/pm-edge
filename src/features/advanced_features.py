"""Advanced feature extraction for LLM news and on-chain signals."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from data.llm_news_processor import LLMNewsSummary
from data.news_sentiment import SentimentVector
from data.onchain_processor import OnChainMetricSnapshot


class AdvancedFeatureInputs(BaseModel):
    """Inputs used to build optional advanced feature columns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    llm_summary: LLMNewsSummary | None = None
    onchain_snapshot: OnChainMetricSnapshot | None = None
    sentiment_vector: SentimentVector | None = None
    news_velocity: dict[str, float] = Field(default_factory=dict)


class AdvancedFeatureExtractor:
    """Flatten advanced data sources into model-ready numeric features."""

    def extract(self, inputs: AdvancedFeatureInputs) -> dict[str, float]:
        """Return advanced features with stable names and defaults."""

        features: dict[str, float] = {
            "llm_news_score": 0.0,
            "llm_news_momentum": 0.0,
            "llm_uncertainty": 0.5,
            "llm_probability": 0.5,
            "onchain_whale_activity": 0.0,
            "onchain_funding_rate": 0.0,
            "onchain_funding_rate_momentum": 0.0,
            "onchain_whale_flow_score": 0.0,
            "onchain_panic_reversion_score": 0.0,
            "onchain_volume_surge": 0.0,
            "onchain_open_interest_change": 0.0,
            "onchain_tvl_change_24h": 0.0,
            "cross_source_agreement": 0.0,
            "cross_source_disagreement": 0.0,
            "news_velocity_6h": 0.0,
            "news_velocity_24h": 0.0,
            "news_velocity_7d": 0.0,
            "news_velocity_ratio_6h_24h": 0.0,
        }
        if inputs.llm_summary is not None:
            features.update(
                {
                    "llm_news_score": inputs.llm_summary.sentiment,
                    "llm_news_momentum": inputs.llm_summary.momentum,
                    "llm_uncertainty": inputs.llm_summary.uncertainty,
                    "llm_probability": inputs.llm_summary.probability_signal,
                }
            )
        if inputs.onchain_snapshot is not None:
            features.update(
                {
                    "onchain_whale_activity": inputs.onchain_snapshot.whale_activity,
                    "onchain_funding_rate": inputs.onchain_snapshot.funding_rate,
                    "onchain_funding_rate_momentum": inputs.onchain_snapshot.funding_rate_momentum,
                    "onchain_whale_flow_score": inputs.onchain_snapshot.whale_flow_score,
                    "onchain_panic_reversion_score": inputs.onchain_snapshot.panic_reversion_score,
                    "onchain_volume_surge": inputs.onchain_snapshot.volume_surge,
                    "onchain_open_interest_change": inputs.onchain_snapshot.open_interest_change,
                    "onchain_tvl_change_24h": inputs.onchain_snapshot.tvl_change_24h,
                }
            )

        velocity = inputs.news_velocity or _velocity_from_sentiment(inputs.sentiment_vector)
        features["news_velocity_6h"] = velocity.get("6h", 0.0)
        features["news_velocity_24h"] = velocity.get("24h", 0.0)
        features["news_velocity_7d"] = velocity.get("7d", 0.0)
        if features["news_velocity_24h"]:
            features["news_velocity_ratio_6h_24h"] = (
                features["news_velocity_6h"] / features["news_velocity_24h"]
            )

        agreement = _agreement(
            llm_score=features["llm_news_score"],
            sentiment_score=(
                inputs.sentiment_vector.sentiment_24h
                if inputs.sentiment_vector is not None
                else 0.0
            ),
            onchain_score=features["onchain_tvl_change_24h"]
            + features["onchain_volume_surge"] * 0.1,
        )
        features["cross_source_agreement"] = agreement
        features["cross_source_disagreement"] = 1.0 - agreement
        return features


def _velocity_from_sentiment(vector: SentimentVector | None) -> dict[str, float]:
    if vector is None:
        return {}
    return {
        "6h": float(vector.mention_count_24h) / 4,
        "24h": float(vector.mention_count_24h),
        "7d": float(vector.mention_count_7d),
    }


def _agreement(*, llm_score: float, sentiment_score: float, onchain_score: float) -> float:
    directional = [
        score for score in [llm_score, sentiment_score, onchain_score] if abs(score) > 0.02
    ]
    if len(directional) < 2:
        return 0.0
    positives = sum(1 for score in directional if score > 0)
    negatives = sum(1 for score in directional if score < 0)
    return max(positives, negatives) / len(directional)
