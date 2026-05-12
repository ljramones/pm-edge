from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from core import OrderBook, UnifiedMarket, Venue
from data.llm_news_processor import LLMNewsSummary
from data.news_sentiment import SentimentVector
from data.poll_aggregator import PollAggregate
from features import FeatureStore


@pytest.mark.asyncio
async def test_feature_store_combines_phase1_inputs() -> None:
    market = UnifiedMarket(
        venue=Venue.POLYMARKET,
        market_id="m-1",
        title="Will BTC hit 100k?",
        outcomes=["Yes", "No"],
    )
    price_history = pd.DataFrame(
        {
            "market_id": ["m-1", "m-2", "m-1", "m-2", "m-1", "m-2"],
            "observed_at": pd.date_range("2026-05-01", periods=6, freq="D", tz=UTC),
            "mid": [0.5, 0.4, 0.52, 0.42, 0.55, 0.45],
        }
    )

    vector = await FeatureStore().build_market_features(
        market,
        event_slug="btc-100k",
        poll_aggregates=[
            PollAggregate(
                event_slug="btc-100k",
                candidate="Yes",
                probability=0.6,
                as_of=datetime(2026, 5, 12, tzinfo=UTC),
                poll_count=2,
            )
        ],
        sentiment_vector=SentimentVector(
            event_slug="btc-100k",
            market_id="m-1",
            as_of=datetime(2026, 5, 12, tzinfo=UTC),
            mention_count_24h=5,
            mention_count_7d=20,
            sentiment_24h=0.2,
            sentiment_7d=0.1,
            tone_shift=0.1,
        ),
        price_history=price_history,
        related_market_id="m-2",
        order_book=OrderBook(
            market_id="m-1",
            bids=[(Decimal("0.54"), Decimal("50"))],
            asks=[(Decimal("0.56"), Decimal("40"))],
        ),
    )

    assert vector.market_probability == 0.55
    assert vector.features["poll_top_probability"] == 0.6
    assert vector.features["mention_count_7d"] == 20
    assert vector.features["book_imbalance"] > 0


@pytest.mark.asyncio
async def test_feature_store_merges_advanced_inputs() -> None:
    as_of = datetime(2026, 5, 12, tzinfo=UTC)
    market = UnifiedMarket(
        venue=Venue.POLYMARKET,
        market_id="m-advanced",
        title="Will BTC rally?",
        outcomes=["Yes", "No"],
    )

    vector = await FeatureStore().build_market_features(
        market,
        llm_summary=LLMNewsSummary(
            market_id="m-advanced",
            market_title="Will BTC rally?",
            as_of=as_of,
            provider="fallback",
            model="lexical",
            article_count=1,
            sentiment=0.2,
            probability_signal=0.58,
        ),
        as_of=as_of,
    )

    assert vector.features["llm_probability"] == 0.58
    assert vector.raw["llm_summary"] is not None
