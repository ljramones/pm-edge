"""Data ingestion, scraping, and external signal aggregation."""

from data.database import HistoricalMarketStore
from data.llm_news_processor import LLMNewsProcessor, LLMNewsSummary
from data.news_sentiment import MarketEntityMap, NewsArticle, NewsSentimentEngine, SentimentVector
from data.onchain_processor import OnChainMetricSnapshot, OnChainProcessor
from data.poll_aggregator import PollAggregate, PollAggregator, PollRecord
from data.resolved_backfill import BackfillConfig, ResolvedMarketBackfill

__all__ = [
    "BackfillConfig",
    "HistoricalMarketStore",
    "LLMNewsProcessor",
    "LLMNewsSummary",
    "MarketEntityMap",
    "NewsArticle",
    "NewsSentimentEngine",
    "OnChainMetricSnapshot",
    "OnChainProcessor",
    "PollAggregate",
    "PollAggregator",
    "PollRecord",
    "ResolvedMarketBackfill",
    "SentimentVector",
]
