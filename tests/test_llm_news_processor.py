from datetime import UTC, datetime, timedelta

import pytest

from core.config import Settings
from data.llm_news_processor import LLMNewsProcessor
from data.news_sentiment import NewsArticle


@pytest.mark.asyncio
async def test_llm_news_processor_fallback_caches_summary(tmp_path) -> None:
    settings = Settings(llm_cache_dir=tmp_path, openai_api_key=None)
    processor = LLMNewsProcessor(settings=settings, cache_dir=tmp_path)
    as_of = datetime(2026, 5, 12, tzinfo=UTC)
    articles = [
        NewsArticle(
            title="Bitcoin gains after bullish ETF inflows",
            published_at=as_of - timedelta(hours=2),
            source="test",
            content="Bitcoin bulls see positive growth and a strong lead.",
        )
    ]

    first = await processor.summarize_market(
        market_id="btc-100k",
        market_title="Will Bitcoin hit 100k?",
        articles=articles,
        as_of=as_of,
    )
    second = await processor.summarize_market(
        market_id="btc-100k",
        market_title="Will Bitcoin hit 100k?",
        articles=articles,
        as_of=as_of,
    )
    await processor.close()

    assert first.fallback_used is True
    assert second.cached is True
    assert second.probability_signal > 0.5
    assert len(list(tmp_path.glob("*.json"))) == 1
