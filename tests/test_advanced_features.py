from datetime import UTC, datetime

from data.llm_news_processor import LLMNewsSummary
from data.news_sentiment import SentimentVector
from data.onchain_processor import OnChainMetricSnapshot
from features.advanced_features import AdvancedFeatureExtractor, AdvancedFeatureInputs


def test_advanced_feature_extractor_combines_sources() -> None:
    as_of = datetime(2026, 5, 12, tzinfo=UTC)
    features = AdvancedFeatureExtractor().extract(
        AdvancedFeatureInputs(
            llm_summary=LLMNewsSummary(
                market_id="m-1",
                market_title="Will ETH rally?",
                as_of=as_of,
                provider="fallback",
                model="lexical",
                article_count=2,
                sentiment=0.3,
                momentum=0.2,
                uncertainty=0.4,
                probability_signal=0.61,
            ),
            onchain_snapshot=OnChainMetricSnapshot(
                market_id="m-1",
                asset_symbol="ETH",
                as_of=as_of,
                whale_activity=0.5,
                volume_surge=0.25,
                tvl_change_24h=0.04,
            ),
            sentiment_vector=SentimentVector(
                event_slug="eth",
                market_id="m-1",
                as_of=as_of,
                mention_count_24h=8,
                mention_count_7d=30,
                sentiment_24h=0.25,
            ),
        )
    )

    assert features["llm_probability"] == 0.61
    assert features["onchain_whale_activity"] == 0.5
    assert features["news_velocity_24h"] == 8
    assert features["cross_source_agreement"] > 0
