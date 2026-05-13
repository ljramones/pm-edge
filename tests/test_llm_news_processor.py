from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from core.config import Settings
from data.llm_news_processor import LLMNewsProcessor
from data.news_sentiment import NewsArticle


@pytest.mark.asyncio
async def test_llm_news_processor_fallback_caches_summary(tmp_path: Path) -> None:
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
    assert len(list(tmp_path.glob("*.json"))) == 1  # noqa: ASYNC240


@pytest.mark.asyncio
async def test_llm_news_processor_uses_ollama_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeAsyncClient:
        def __init__(self, *, host: str) -> None:
            self.host = host

        async def chat(self, **_: Any) -> dict[str, Any]:
            return {
                "message": {
                    "content": (
                        '{"key_events":["ETF inflows accelerated"],"sentiment":0.4,'
                        '"momentum":0.2,"uncertainty":0.3,"probability_signal":0.62,'
                        '"impact":"positive","reasoning":"Local model saw bullish flow."}'
                    )
                }
            }

    class FakeOllama:
        AsyncClient = FakeAsyncClient

    def fake_import_module(name: str) -> Any:
        if name == "ollama":
            return FakeOllama
        raise ImportError(name)

    monkeypatch.setattr("importlib.import_module", fake_import_module)

    settings = Settings(
        llm_provider="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:32b",
        llm_cache_dir=tmp_path,
        high_value_fallback=False,
    )
    processor = LLMNewsProcessor(settings=settings, cache_dir=tmp_path)
    as_of = datetime(2026, 5, 12, tzinfo=UTC)
    summary = await processor.summarize_market(
        market_id="btc-100k",
        market_title="Will Bitcoin hit 100k?",
        articles=[
            NewsArticle(
                title="Bitcoin ETF inflows accelerate",
                published_at=as_of - timedelta(hours=1),
                source="test",
                content="ETF inflows accelerated and liquidity improved.",
            )
        ],
        as_of=as_of,
    )
    await processor.close()

    assert summary.provider == "ollama"
    assert summary.model == "qwen2.5:32b"
    assert summary.fallback_used is False
    assert summary.probability_signal == 0.62
