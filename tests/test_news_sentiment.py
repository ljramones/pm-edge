from datetime import UTC, datetime, timedelta

from data.news_sentiment import MarketEntityMap, NewsArticle, NewsSentimentEngine


def test_news_sentiment_links_articles_and_computes_velocity() -> None:
    as_of = datetime(2026, 5, 12, tzinfo=UTC)
    engine = NewsSentimentEngine(
        [
            MarketEntityMap(
                event_slug="btc-100k",
                market_id="m-btc",
                keywords=["Bitcoin", "BTC"],
            )
        ]
    )
    articles = [
        NewsArticle(
            title="Bitcoin bulls surge after positive ETF flows",
            published_at=as_of - timedelta(hours=2),
        ),
        NewsArticle(
            title="BTC risk rises after bearish market decline",
            published_at=as_of - timedelta(days=3),
        ),
    ]

    vectors = engine.compute_vectors(articles, as_of=as_of)

    assert len(vectors) == 1
    assert vectors[0].mention_count_24h == 1
    assert vectors[0].mention_count_7d == 2
    assert vectors[0].market_id == "m-btc"
