"""Unified Phase 1 feature generation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from core.client import OrderBook, PredictionMarketClient, UnifiedMarket
from core.models import FeatureVectorRecord, utc_now
from data.llm_news_processor import LLMNewsSummary
from data.news_sentiment import SentimentVector
from data.onchain_processor import OnChainMetricSnapshot
from data.poll_aggregator import PollAggregate
from features.advanced_features import AdvancedFeatureExtractor, AdvancedFeatureInputs
from features.cross_market import CrossMarketAnalyzer, CrossMarketFeatureSet
from utils.logging import get_logger

logger = get_logger(__name__)


class FeatureVector(BaseModel):
    """Feature vector for one market at one scoring timestamp."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    event_slug: str | None = None
    as_of: datetime
    features: dict[str, float] = Field(default_factory=dict)
    market_probability: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    def to_frame(self) -> pd.DataFrame:
        """Return a one-row pandas DataFrame."""

        return pd.DataFrame([{**self.features, "market_id": self.market_id, "as_of": self.as_of}])


class FeatureStore:
    """Combine poll, sentiment, cross-market, and microstructure features."""

    def __init__(
        self,
        *,
        client: PredictionMarketClient | None = None,
        cross_market_analyzer: CrossMarketAnalyzer | None = None,
        advanced_extractor: AdvancedFeatureExtractor | None = None,
    ) -> None:
        self.client = client
        self.cross_market_analyzer = cross_market_analyzer or CrossMarketAnalyzer()
        self.advanced_extractor = advanced_extractor or AdvancedFeatureExtractor()

    async def build_market_features(
        self,
        market: UnifiedMarket,
        *,
        event_slug: str | None = None,
        poll_aggregates: list[PollAggregate] | None = None,
        sentiment_vector: SentimentVector | None = None,
        price_history: pd.DataFrame | None = None,
        related_market_id: str | None = None,
        resolution_stats: dict[str, float] | None = None,
        order_book: OrderBook | None = None,
        advanced_features: dict[str, float] | None = None,
        llm_summary: LLMNewsSummary | None = None,
        onchain_snapshot: OnChainMetricSnapshot | None = None,
        news_velocity: dict[str, float] | None = None,
        as_of: datetime | None = None,
    ) -> FeatureVector:
        """Build a single market feature vector."""

        snapshot_time = as_of or utc_now()
        book = order_book
        if book is None and self.client is not None:
            book = await self.client.fetch_order_book(market.market_id, market.venue)

        cross_market = (
            self.cross_market_analyzer.compute(
                price_history,
                target_market_id=market.market_id,
                related_market_id=related_market_id,
            )
            if price_history is not None
            else CrossMarketFeatureSet(
                market_id=market.market_id, related_market_id=related_market_id
            )
        )

        features: dict[str, float] = {}
        features.update(poll_features(poll_aggregates or []))
        features.update(sentiment_features(sentiment_vector))
        features.update(cross_market_features(cross_market))
        features.update(microstructure_features(book))
        features.update(resolution_stats or {})
        if advanced_features is not None:
            features.update(advanced_features)
        elif llm_summary is not None or onchain_snapshot is not None or news_velocity is not None:
            features.update(
                self.advanced_extractor.extract(
                    AdvancedFeatureInputs(
                        llm_summary=llm_summary,
                        onchain_snapshot=onchain_snapshot,
                        sentiment_vector=sentiment_vector,
                        news_velocity=news_velocity or {},
                    )
                )
            )

        market_probability = _market_probability(book)
        logger.info(
            "features_built",
            market_id=market.market_id,
            event_slug=event_slug,
            feature_count=len(features),
        )
        return FeatureVector(
            market_id=market.market_id,
            event_slug=event_slug,
            as_of=snapshot_time,
            features=features,
            market_probability=market_probability,
            raw={
                "market": market.model_dump(mode="json"),
                "llm_summary": llm_summary.model_dump(mode="json") if llm_summary else None,
                "onchain_snapshot": (
                    onchain_snapshot.model_dump(mode="json") if onchain_snapshot else None
                ),
            },
        )

    def materialize_record(
        self,
        vector: FeatureVector,
        *,
        resolved_probability: float | None = None,
    ) -> FeatureVectorRecord:
        """Convert a runtime feature vector to a SQLModel record."""

        return FeatureVectorRecord(
            market_id=vector.market_id,
            event_slug=vector.event_slug,
            as_of=vector.as_of,
            features=vector.features,
            market_probability=(
                Decimal(str(vector.market_probability))
                if vector.market_probability is not None
                else None
            ),
            resolved_probability=(
                Decimal(str(resolved_probability)) if resolved_probability is not None else None
            ),
        )


def poll_features(aggregates: list[PollAggregate]) -> dict[str, float]:
    """Flatten latest poll aggregates into model features."""

    if not aggregates:
        return {"poll_top_probability": 0.5, "poll_spread": 0.0, "poll_count": 0.0}

    probabilities = sorted((aggregate.probability for aggregate in aggregates), reverse=True)
    top = probabilities[0]
    second = probabilities[1] if len(probabilities) > 1 else 1 - top
    return {
        "poll_top_probability": top,
        "poll_spread": top - second,
        "poll_count": float(sum(aggregate.poll_count for aggregate in aggregates)),
        "poll_effective_sample_size": float(
            sum(aggregate.effective_sample_size for aggregate in aggregates)
        ),
    }


def sentiment_features(vector: SentimentVector | None) -> dict[str, float]:
    """Flatten sentiment vector into numeric model features."""

    if vector is None:
        return {
            "mention_count_24h": 0.0,
            "mention_count_7d": 0.0,
            "sentiment_24h": 0.0,
            "sentiment_7d": 0.0,
            "tone_shift": 0.0,
        }
    return {
        "mention_count_24h": float(vector.mention_count_24h),
        "mention_count_7d": float(vector.mention_count_7d),
        "sentiment_24h": vector.sentiment_24h,
        "sentiment_7d": vector.sentiment_7d,
        "tone_shift": vector.tone_shift,
    }


def cross_market_features(features: CrossMarketFeatureSet) -> dict[str, float]:
    """Flatten cross-market feature object."""

    return {
        "price_divergence": features.price_divergence,
        "rolling_corr_7d": features.rolling_corr_7d,
        "rolling_corr_30d": features.rolling_corr_30d,
        "lead_lag_corr_1d": features.lead_lag_corr_1d,
        "implied_conditional_probability": features.implied_conditional_probability,
    }


def microstructure_features(order_book: OrderBook | None) -> dict[str, float]:
    """Compute order book imbalance, spread, and liquidity features."""

    if order_book is None:
        return {
            "best_bid": 0.0,
            "best_ask": 0.0,
            "spread": 0.0,
            "book_imbalance": 0.0,
            "top_book_liquidity": 0.0,
        }

    best_bid = max((price for price, _size in order_book.bids), default=Decimal("0"))
    best_ask = min((price for price, _size in order_book.asks), default=Decimal("0"))
    bid_size = sum(size for _price, size in order_book.bids)
    ask_size = sum(size for _price, size in order_book.asks)
    total_size = bid_size + ask_size
    imbalance = (bid_size - ask_size) / total_size if total_size else Decimal("0")
    spread = best_ask - best_bid if best_bid and best_ask else Decimal("0")

    return {
        "best_bid": float(best_bid),
        "best_ask": float(best_ask),
        "spread": float(spread),
        "book_imbalance": float(imbalance),
        "top_book_liquidity": float(total_size),
    }


def _market_probability(order_book: OrderBook | None) -> float | None:
    if order_book is None:
        return None
    features = microstructure_features(order_book)
    bid = features["best_bid"]
    ask = features["best_ask"]
    if bid and ask:
        return (bid + ask) / 2
    return bid or ask or None
