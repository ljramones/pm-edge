"""LLM-assisted news summaries and probabilistic market signals.

The processor is deliberately conservative: it uses direct provider APIs when
credentials are available, caches every market/article batch, and falls back to
deterministic lexical scoring when the LLM path is unavailable.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from core.config import Settings, get_settings
from core.models import utc_now
from data.news_sentiment import NEGATIVE_WORDS, POSITIVE_WORDS, NewsArticle
from utils.logging import get_logger

logger = get_logger(__name__)

LLMProvider = Literal["ollama", "openai", "claude", "grok"]
FrontierLLMProvider = Literal["openai", "claude", "grok"]


class LLMCostEstimate(BaseModel):
    """Approximate LLM usage and cost for one request."""

    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    provider: LLMProvider
    model: str


class LLMNewsSummary(BaseModel):
    """Structured LLM or fallback summary linked to one market."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    market_title: str
    as_of: datetime
    provider: LLMProvider | Literal["fallback"]
    model: str
    article_count: int
    key_events: list[str] = Field(default_factory=list)
    sentiment: float = Field(default=0.0, ge=-1.0, le=1.0)
    momentum: float = Field(default=0.0, ge=-1.0, le=1.0)
    uncertainty: float = Field(default=0.5, ge=0.0, le=1.0)
    probability_signal: float = Field(default=0.5, ge=0.0, le=1.0)
    impact: str = "neutral"
    reasoning: str = ""
    cached: bool = False
    fallback_used: bool = False
    prompt_hash: str | None = None
    response_hash: str | None = None
    cost_estimate: LLMCostEstimate | None = None


class LLMNewsProcessor:
    """Generate cached, structured news signals using a configurable LLM provider."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds
        )
        self._owns_http_client = http_client is None
        self.cache_dir = cache_dir or self.settings.llm_cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request_at: float | None = None

    async def close(self) -> None:
        """Close owned network resources."""

        if self._owns_http_client:
            await self.http_client.aclose()

    async def summarize_market(
        self,
        *,
        market_id: str,
        market_title: str,
        articles: list[NewsArticle],
        provider: LLMProvider | None = None,
        as_of: datetime | None = None,
        high_value: bool = False,
    ) -> LLMNewsSummary:
        """Return a structured news summary for a market/article batch."""

        anchor = as_of or utc_now()
        selected_provider = provider or self.settings.llm_provider
        high_value_call = high_value or self._is_high_value_call(
            provider=selected_provider,
            market_title=market_title,
            articles=articles,
        )
        model = self._model_for(selected_provider, high_value=high_value_call)
        prompt = self._build_prompt(market_title, articles, anchor)
        prompt_hash = _hash_text(prompt)
        cache_path = self._cache_path(market_id, selected_provider, model, articles, prompt_hash)
        if cache_path.exists():
            summary = LLMNewsSummary.model_validate_json(cache_path.read_text())
            return summary.model_copy(update={"cached": True})

        cost = estimate_llm_cost(
            prompt,
            provider=selected_provider,
            model=model,
            completion_tokens=650,
        )
        if not self.has_credentials(selected_provider):
            summary = self._fallback_summary(
                market_id=market_id,
                market_title=market_title,
                articles=articles,
                as_of=anchor,
                prompt_hash=prompt_hash,
                cost=cost,
            )
            self._write_cache(cache_path, summary, prompt=prompt, raw_response=None)
            return summary

        await self._respect_rate_limit()
        used_provider = selected_provider
        used_model = model
        used_cost = cost
        fallback_used = (
            selected_provider == "ollama" and model == self.settings.ollama_fallback_model
        )
        if fallback_used:
            logger.info(
                "llm_news_summary_high_value_ollama_model",
                market_id=market_id,
                provider=selected_provider,
                model=model,
                fallback_threshold=self.settings.llm_fallback_threshold,
            )
        try:
            raw_text = await self._call_provider(used_provider, used_model, prompt)
        except Exception as exc:
            raw_text = None
            if (
                selected_provider == "ollama"
                and used_provider == "ollama"
                and used_model != self.settings.ollama_fallback_model
                and self.settings.high_value_fallback
            ):
                logger.warning(
                    "llm_news_summary_local_fallback",
                    market_id=market_id,
                    provider=selected_provider,
                    model=used_model,
                    fallback_model=self.settings.ollama_fallback_model,
                    error=str(exc),
                )
                await self._respect_rate_limit()
                try:
                    raw_text = await self._call_provider(
                        "ollama", self.settings.ollama_fallback_model, prompt
                    )
                    used_model = self.settings.ollama_fallback_model
                    used_cost = estimate_llm_cost(
                        prompt,
                        provider="ollama",
                        model=used_model,
                        completion_tokens=650,
                    )
                    fallback_used = True
                except Exception as local_fallback_exc:
                    logger.warning(
                        "llm_news_summary_local_fallback_failed",
                        market_id=market_id,
                        provider=selected_provider,
                        fallback_model=self.settings.ollama_fallback_model,
                        error=str(local_fallback_exc),
                    )

            if (
                raw_text is None
                and used_provider == selected_provider
                and self._should_try_frontier_fallback(selected_provider, model)
            ):
                fallback_provider = self.settings.llm_fallback_provider
                fallback_model = self._model_for(fallback_provider)
                if self.has_credentials(fallback_provider):
                    logger.warning(
                        "llm_news_summary_frontier_fallback",
                        market_id=market_id,
                        provider=selected_provider,
                        model=model,
                        fallback_provider=fallback_provider,
                        fallback_model=fallback_model,
                        error=str(exc),
                    )
                    await self._respect_rate_limit()
                    try:
                        raw_text = await self._call_provider(
                            fallback_provider, fallback_model, prompt
                        )
                        used_provider = fallback_provider
                        used_model = fallback_model
                        used_cost = estimate_llm_cost(
                            prompt,
                            provider=used_provider,
                            model=used_model,
                            completion_tokens=650,
                        )
                        fallback_used = True
                    except Exception as fallback_exc:
                        logger.warning(
                            "llm_news_summary_frontier_fallback_failed",
                            market_id=market_id,
                            provider=selected_provider,
                            fallback_provider=fallback_provider,
                            error=str(fallback_exc),
                        )
                        raw_text = None
                else:
                    raw_text = None

            if raw_text is None:
                logger.warning(
                    "llm_news_summary_failed",
                    market_id=market_id,
                    provider=selected_provider,
                    error=str(exc),
                )
                summary = self._fallback_summary(
                    market_id=market_id,
                    market_title=market_title,
                    articles=articles,
                    as_of=anchor,
                    prompt_hash=prompt_hash,
                    cost=cost,
                )
                self._write_cache(cache_path, summary, prompt=prompt, raw_response=None)
                return summary

        try:
            assert raw_text is not None
            parsed = _parse_json_object(raw_text)
            summary = LLMNewsSummary(
                market_id=market_id,
                market_title=market_title,
                as_of=anchor,
                provider=used_provider,
                model=used_model,
                article_count=len(articles),
                key_events=[str(item) for item in parsed.get("key_events", [])][:8],
                sentiment=_bounded_float(parsed.get("sentiment"), -1.0, 1.0, 0.0),
                momentum=_bounded_float(parsed.get("momentum"), -1.0, 1.0, 0.0),
                uncertainty=_bounded_float(parsed.get("uncertainty"), 0.0, 1.0, 0.5),
                probability_signal=_bounded_float(parsed.get("probability_signal"), 0.0, 1.0, 0.5),
                impact=str(parsed.get("impact") or "neutral"),
                reasoning=str(parsed.get("reasoning") or ""),
                fallback_used=fallback_used,
                prompt_hash=prompt_hash,
                response_hash=_hash_text(raw_text),
                cost_estimate=used_cost,
            )
            self._write_cache(cache_path, summary, prompt=prompt, raw_response=raw_text)
            logger.info(
                "llm_news_summary_generated",
                market_id=market_id,
                provider=used_provider,
                model=used_model,
                requested_provider=selected_provider,
                article_count=len(articles),
                estimated_cost_usd=used_cost.estimated_cost_usd,
                prompt_hash=prompt_hash,
            )
            return summary
        except Exception as exc:
            logger.warning(
                "llm_news_summary_failed",
                market_id=market_id,
                provider=selected_provider,
                error=str(exc),
            )
            summary = self._fallback_summary(
                market_id=market_id,
                market_title=market_title,
                articles=articles,
                as_of=anchor,
                prompt_hash=prompt_hash,
                cost=cost,
            )
            self._write_cache(cache_path, summary, prompt=prompt, raw_response=None)
            return summary

    def estimate_batch_cost(
        self,
        *,
        market_count: int,
        articles_per_market: int,
        provider: LLMProvider | None = None,
    ) -> LLMCostEstimate:
        """Estimate total cost for a planned signal-generation batch."""

        selected_provider = provider or self.settings.llm_provider
        model = self._model_for(selected_provider)
        synthetic_article = " ".join(["market-relevant article text"] * 120)
        prompt = self._build_prompt(
            "Example market",
            [
                NewsArticle(
                    title=f"Example article {index}",
                    published_at=utc_now(),
                    source="estimate",
                    content=synthetic_article,
                )
                for index in range(articles_per_market)
            ],
            utc_now(),
        )
        per_market = estimate_llm_cost(
            prompt,
            provider=selected_provider,
            model=model,
            completion_tokens=650,
        )
        return LLMCostEstimate(
            prompt_tokens=per_market.prompt_tokens * market_count,
            completion_tokens=per_market.completion_tokens * market_count,
            estimated_cost_usd=per_market.estimated_cost_usd * market_count,
            provider=selected_provider,
            model=model,
        )

    def has_credentials(self, provider: LLMProvider | None = None) -> bool:
        """Return whether the selected provider can be attempted."""

        selected = provider or self.settings.llm_provider
        if selected == "ollama":
            return True
        return self._api_key(selected) is not None

    async def _call_provider(self, provider: LLMProvider, model: str, prompt: str) -> str:
        if provider == "ollama":
            return await self._call_ollama(model, prompt)

        if provider == "claude":
            response = await self.http_client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key(provider) or "",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model,
                    "max_tokens": 650,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()
            content = payload.get("content", [])
            return "\n".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )

        base_url = (
            "https://api.x.ai/v1/chat/completions"
            if provider == "grok"
            else "https://api.openai.com/v1/chat/completions"
        )
        response = await self.http_client.post(
            base_url,
            headers={"Authorization": f"Bearer {self._api_key(provider) or ''}"},
            json={
                "model": model,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return only valid compact JSON for prediction-market research.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])

    async def _call_ollama(self, model: str, prompt: str) -> str:
        try:
            ollama = importlib.import_module("ollama")
        except ImportError as exc:
            raise RuntimeError(
                "The ollama package is not installed. Run `pip install -e .` or install ollama."
            ) from exc

        client = ollama.AsyncClient(host=self.settings.ollama_host)
        response = await client.chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Return only valid compact JSON for prediction-market research.",
                },
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.1},
        )
        message = response.get("message", {}) if isinstance(response, dict) else response.message
        if isinstance(message, dict):
            return str(message.get("content", ""))
        return str(getattr(message, "content", ""))

    async def _respect_rate_limit(self) -> None:
        now = asyncio.get_running_loop().time()
        min_gap = 60.0 / self.settings.llm_max_requests_per_minute
        if self._last_request_at is not None:
            await asyncio.sleep(max(0.0, min_gap - (now - self._last_request_at)))
        self._last_request_at = asyncio.get_running_loop().time()

    def _fallback_summary(
        self,
        *,
        market_id: str,
        market_title: str,
        articles: list[NewsArticle],
        as_of: datetime,
        prompt_hash: str,
        cost: LLMCostEstimate,
    ) -> LLMNewsSummary:
        scores = [_lexicon_sentiment(article.text) for article in articles]
        recent_scores = [
            score
            for article, score in zip(articles, scores, strict=False)
            if (as_of - article.published_at).total_seconds() <= 24 * 3600
        ]
        sentiment = _mean(scores)
        momentum = _mean(recent_scores) - sentiment
        uncertainty = max(0.15, min(0.85, 0.65 - min(len(articles), 10) * 0.035))
        probability_signal = max(0.01, min(0.99, 0.5 + 0.22 * sentiment + 0.12 * momentum))
        key_events = [article.title for article in articles[:5]]
        return LLMNewsSummary(
            market_id=market_id,
            market_title=market_title,
            as_of=as_of,
            provider="fallback",
            model="lexical-fallback",
            article_count=len(articles),
            key_events=key_events,
            sentiment=sentiment,
            momentum=momentum,
            uncertainty=uncertainty,
            probability_signal=probability_signal,
            impact=(
                "positive" if sentiment > 0.05 else "negative" if sentiment < -0.05 else "neutral"
            ),
            reasoning="Fallback lexical summary used because no configured LLM response was available.",
            fallback_used=True,
            prompt_hash=prompt_hash,
            cost_estimate=cost,
        )

    def _build_prompt(self, market_title: str, articles: list[NewsArticle], as_of: datetime) -> str:
        article_lines = []
        for index, article in enumerate(articles[:12], start=1):
            text = article.text.replace("\n", " ")
            article_lines.append(
                f"{index}. [{article.published_at.isoformat()}] {article.source or 'unknown'}: "
                f"{text[:900]}"
            )
        return (
            "Analyze the following news only as of the timestamp below. Do not use future "
            "knowledge. Return JSON with keys: key_events (list), sentiment (-1..1), "
            "momentum (-1..1), uncertainty (0..1), probability_signal (0..1), impact, "
            "reasoning.\n\n"
            f"As of: {as_of.isoformat()}\nMarket: {market_title}\nArticles:\n"
            + "\n".join(article_lines)
        )

    def _api_key(self, provider: FrontierLLMProvider) -> str | None:
        key = {
            "openai": self.settings.openai_api_key,
            "claude": self.settings.anthropic_api_key,
            "grok": self.settings.grok_api_key,
        }[provider]
        return key.get_secret_value() if key is not None else None

    def _model_for(self, provider: LLMProvider, *, high_value: bool = False) -> str:
        if self.settings.llm_model:
            return self.settings.llm_model
        if provider == "ollama":
            if high_value and self.settings.high_value_fallback:
                return self.settings.ollama_fallback_model
            return self.settings.ollama_model
        if self.settings.llm_fallback_model and provider == self.settings.llm_fallback_provider:
            return self.settings.llm_fallback_model
        return {
            "openai": "gpt-4o-mini",
            "claude": "claude-3-5-haiku-latest",
            "grok": "grok-3-mini",
        }[provider]

    def _should_try_frontier_fallback(self, provider: LLMProvider, model: str) -> bool:
        return provider == "ollama" and self.settings.high_value_fallback

    def _is_high_value_call(
        self,
        *,
        provider: LLMProvider,
        market_title: str,
        articles: list[NewsArticle],
    ) -> bool:
        if provider != "ollama" or not self.settings.high_value_fallback:
            return False
        article_chars = sum(len(article.text) for article in articles)
        complexity = min(
            1.0,
            (min(len(articles), 12) / 12.0) * 0.45
            + (min(len(market_title), 180) / 180.0) * 0.20
            + (min(article_chars, 7_500) / 7_500.0) * 0.35,
        )
        return complexity >= self.settings.llm_fallback_threshold

    def _cache_path(
        self,
        market_id: str,
        provider: LLMProvider,
        model: str,
        articles: list[NewsArticle],
        prompt_hash: str,
    ) -> Path:
        articles_hash = _hash_text(
            json.dumps(
                [
                    {
                        "title": article.title,
                        "published_at": article.published_at.isoformat(),
                        "url": article.url,
                    }
                    for article in articles
                ],
                sort_keys=True,
            )
        )
        name = _safe_name(f"{market_id}-{provider}-{model}-{prompt_hash[:10]}-{articles_hash[:10]}")
        return self.cache_dir / f"{name}.json"

    def _write_cache(
        self,
        path: Path,
        summary: LLMNewsSummary,
        *,
        prompt: str,
        raw_response: str | None,
    ) -> None:
        payload = summary.model_dump(mode="json")
        payload["audit"] = {
            "prompt": prompt,
            "raw_response": raw_response,
            "written_at": utc_now().isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def estimate_llm_cost(
    prompt: str,
    *,
    provider: LLMProvider,
    model: str,
    completion_tokens: int = 650,
) -> LLMCostEstimate:
    """Estimate token usage and USD cost with conservative static pricing."""

    prompt_tokens = max(1, len(prompt) // 4)
    input_per_million, output_per_million = {
        "ollama": (0.0, 0.0),
        "openai": (0.15, 0.60),
        "claude": (0.80, 4.00),
        "grok": (0.30, 0.50),
    }[provider]
    cost = (prompt_tokens / 1_000_000) * input_per_million
    cost += (completion_tokens / 1_000_000) * output_per_million
    return LLMCostEstimate(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
        provider=provider,
        model=model,
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match is None:
            return {}
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else {}


def _lexicon_sentiment(text: str) -> float:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return 0.0
    score = sum(1 for word in words if word in POSITIVE_WORDS)
    score -= sum(1 for word in words if word in NEGATIVE_WORDS)
    return float(max(-1.0, min(1.0, score / max(len(words) ** 0.5, 1.0))))


def _bounded_float(value: Any, lower: float, upper: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(upper, number))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value)[:180]
