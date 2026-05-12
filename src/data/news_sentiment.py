"""News ingestion, entity linking, and sentiment velocity features."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine
from sqlmodel import Session

from core.config import Settings, get_settings
from core.models import SentimentVectorRecord, utc_now
from data.database import HistoricalMarketStore
from utils.logging import get_logger

logger = get_logger(__name__)

POSITIVE_WORDS = {
    "beat",
    "bullish",
    "gain",
    "growth",
    "lead",
    "leading",
    "positive",
    "surge",
    "up",
    "win",
}
NEGATIVE_WORDS = {
    "bearish",
    "decline",
    "down",
    "fall",
    "lag",
    "loss",
    "negative",
    "risk",
    "scandal",
    "slump",
}


class NewsArticle(BaseModel):
    """Normalized news article or RSS item."""

    model_config = ConfigDict(frozen=True)

    title: str
    published_at: datetime
    source: str | None = None
    url: str | None = None
    description: str | None = None
    content: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def text(self) -> str:
        """Return searchable article text."""

        return " ".join(part for part in [self.title, self.description, self.content] if part)


class MarketEntityMap(BaseModel):
    """Keyword/entity mapping for one market or event."""

    event_slug: str
    keywords: list[str]
    market_id: str | None = None


class SentimentVector(BaseModel):
    """Daily sentiment and velocity features linked to one event/market."""

    event_slug: str
    as_of: datetime
    market_id: str | None = None
    mention_count_24h: int = 0
    mention_count_7d: int = 0
    sentiment_24h: float = 0.0
    sentiment_7d: float = 0.0
    tone_shift: float = 0.0
    linked_entities: list[str] = Field(default_factory=list)


class EntityLinker:
    """Simple keyword linker from article text to market/event identifiers."""

    def __init__(self, mappings: Sequence[MarketEntityMap]) -> None:
        self.mappings = mappings

    def link(self, article: NewsArticle) -> list[MarketEntityMap]:
        """Return mappings whose keywords appear in the article text."""

        text = article.text.lower()
        matches: list[MarketEntityMap] = []
        for mapping in self.mappings:
            if any(
                re.search(rf"\b{re.escape(keyword.lower())}\b", text)
                for keyword in mapping.keywords
            ):
                matches.append(mapping)
        return matches


class NewsSentimentEngine:
    """Fetch, link, score, and persist news sentiment velocity features."""

    def __init__(
        self,
        mappings: Sequence[MarketEntityMap] | None = None,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = HistoricalMarketStore(engine=engine, settings=self.settings)
        self.linker = EntityLinker(mappings or [])
        self.http_client = http_client or httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds
        )
        self._owns_http_client = http_client is None
        self._vader = self._load_vader()

    async def close(self) -> None:
        """Close owned network resources."""

        if self._owns_http_client:
            await self.http_client.aclose()

    async def fetch_newsapi(
        self, query: str, *, from_time: datetime | None = None
    ) -> list[NewsArticle]:
        """Fetch normalized articles from NewsAPI when credentials are configured."""

        if self.settings.news_api_key is None:
            return []

        params: dict[str, str] = {
            "q": query,
            "sortBy": "publishedAt",
            "apiKey": self.settings.news_api_key.get_secret_value(),
        }
        if from_time is not None:
            params["from"] = from_time.isoformat()

        response = await self.http_client.get("https://newsapi.org/v2/everything", params=params)
        response.raise_for_status()
        payload = response.json()
        return [
            NewsArticle(
                title=str(item.get("title") or ""),
                description=item.get("description"),
                content=item.get("content"),
                source=(item.get("source") or {}).get("name"),
                url=item.get("url"),
                published_at=_parse_datetime(item.get("publishedAt")),
                raw=item,
            )
            for item in payload.get("articles", [])
            if item.get("title") and item.get("publishedAt")
        ]

    async def fetch_gdelt(self, query: str, *, max_records: int = 250) -> list[NewsArticle]:
        """Fetch normalized articles from GDELT's document API."""

        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(max_records),
            "sort": "HybridRel",
        }
        response = await self.http_client.get(
            "https://api.gdeltproject.org/api/v2/doc/doc", params=params
        )
        response.raise_for_status()
        payload = response.json()
        return [
            NewsArticle(
                title=str(item.get("title") or ""),
                source=item.get("sourceCountry") or item.get("domain"),
                url=item.get("url"),
                published_at=_parse_datetime(item.get("seendate")),
                raw=item,
            )
            for item in payload.get("articles", [])
            if item.get("title") and item.get("seendate")
        ]

    def compute_vectors(
        self,
        articles: Sequence[NewsArticle],
        *,
        as_of: datetime | None = None,
    ) -> list[SentimentVector]:
        """Compute mention velocity and tone-shift features for linked markets."""

        anchor = as_of or utc_now()
        vectors: dict[tuple[str, str | None], list[tuple[NewsArticle, float]]] = {}
        for article in articles:
            score = self.score_article(article)
            for mapping in self.linker.link(article):
                vectors.setdefault((mapping.event_slug, mapping.market_id), []).append(
                    (article, score)
                )

        output: list[SentimentVector] = []
        for (event_slug, market_id), linked_articles in vectors.items():
            last_24h = [
                score
                for article, score in linked_articles
                if anchor - article.published_at <= timedelta(hours=24)
            ]
            last_7d = [
                score
                for article, score in linked_articles
                if anchor - article.published_at <= timedelta(days=7)
            ]
            sentiment_24h = _mean(last_24h)
            sentiment_7d = _mean(last_7d)
            output.append(
                SentimentVector(
                    event_slug=event_slug,
                    market_id=market_id,
                    as_of=anchor,
                    mention_count_24h=len(last_24h),
                    mention_count_7d=len(last_7d),
                    sentiment_24h=sentiment_24h,
                    sentiment_7d=sentiment_7d,
                    tone_shift=sentiment_24h - sentiment_7d,
                    linked_entities=sorted(
                        {
                            keyword
                            for mapping in self.linker.mappings
                            if mapping.event_slug == event_slug and mapping.market_id == market_id
                            for keyword in mapping.keywords
                        }
                    ),
                )
            )

        return output

    def save_vectors(self, vectors: Sequence[SentimentVector]) -> list[SentimentVectorRecord]:
        """Persist sentiment vectors."""

        self.store.init_db()
        rows = [
            SentimentVectorRecord(
                event_slug=vector.event_slug,
                market_id=vector.market_id,
                as_of=vector.as_of,
                mention_count_24h=vector.mention_count_24h,
                mention_count_7d=vector.mention_count_7d,
                sentiment_24h=Decimal(str(vector.sentiment_24h)),
                sentiment_7d=Decimal(str(vector.sentiment_7d)),
                tone_shift=Decimal(str(vector.tone_shift)),
                linked_entities=vector.linked_entities,
                raw=vector.model_dump(mode="json"),
            )
            for vector in vectors
        ]
        with Session(self.store.engine) as session:
            session.add_all(rows)
            session.commit()
            for row in rows:
                session.refresh(row)
        return rows

    def score_article(self, article: NewsArticle) -> float:
        """Return sentiment in [-1, 1] using VADER when available."""

        if self._vader is not None:
            return float(self._vader.polarity_scores(article.text)["compound"])
        return _lexicon_sentiment(article.text)

    def _load_vader(self) -> Any | None:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        except ImportError:
            return None
        return SentimentIntensityAnalyzer()


def vectors_by_market(vectors: Iterable[SentimentVector]) -> Mapping[str, SentimentVector]:
    """Return a market-id keyed view of sentiment vectors."""

    return {vector.market_id: vector for vector in vectors if vector.market_id is not None}


def _lexicon_sentiment(text: str) -> float:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return 0.0
    score = sum(1 for word in words if word in POSITIVE_WORDS)
    score -= sum(1 for word in words if word in NEGATIVE_WORDS)
    return cast(float, max(-1.0, min(1.0, score / max(len(words) ** 0.5, 1.0))))


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value)
        if len(raw) == 14 and raw.isdigit():
            parsed = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
