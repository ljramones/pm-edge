from decimal import Decimal

import pytest

from core import OrderBook, UnifiedMarket, Venue
from data.llm_news_processor import LLMNewsSummary
from features import FeatureStore
from strategies import EdgeDetector


@pytest.mark.asyncio
async def test_edge_detector_returns_edge_signal() -> None:
    market = UnifiedMarket(
        venue=Venue.POLYMARKET,
        market_id="m-1",
        title="Will event happen?",
        outcomes=["Yes", "No"],
    )
    detector = EdgeDetector(FeatureStore())

    signal = await detector.score_market(
        market,
        model_context={
            "order_book": OrderBook(
                market_id="m-1",
                bids=[(Decimal("0.40"), Decimal("10"))],
                asks=[(Decimal("0.42"), Decimal("12"))],
            )
        },
    )

    assert signal.market_id == "m-1"
    assert 0 <= signal.confidence <= 1
    assert signal.edge == pytest.approx(signal.model_prob - signal.market_prob)


@pytest.mark.asyncio
async def test_edge_detector_uses_advanced_features_when_enabled() -> None:
    market = UnifiedMarket(
        venue=Venue.POLYMARKET,
        market_id="m-advanced",
        title="Will event happen?",
        outcomes=["Yes", "No"],
    )
    detector = EdgeDetector(FeatureStore(), use_advanced_features=True)

    signal = await detector.score_market(
        market,
        model_context={
            "llm_summary": LLMNewsSummary(
                market_id="m-advanced",
                market_title="Will event happen?",
                as_of="2026-05-12T00:00:00Z",
                provider="fallback",
                model="lexical",
                article_count=1,
                sentiment=0.4,
                momentum=0.2,
                uncertainty=0.2,
                probability_signal=0.7,
            )
        },
    )

    assert signal.model_prob > 0.5
    assert any("advanced llm probability" in reason for reason in signal.reasoning)
