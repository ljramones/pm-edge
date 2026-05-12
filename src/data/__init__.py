"""Data ingestion, scraping, and external signal aggregation."""

from data.database import HistoricalMarketStore
from data.news_sentiment import MarketEntityMap, NewsArticle, NewsSentimentEngine, SentimentVector
from data.poll_aggregator import PollAggregate, PollAggregator, PollRecord

__all__ = [
    "HistoricalMarketStore",
    "MarketEntityMap",
    "NewsArticle",
    "NewsSentimentEngine",
    "PollAggregate",
    "PollAggregator",
    "PollRecord",
    "SentimentVector",
]
