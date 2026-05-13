from __future__ import annotations

from features import EnhancedOnChainFeatureExtractor, MicroRoundFeatureExtractor


def test_enhanced_onchain_features_capture_tail_and_flow_pressure() -> None:
    features = EnhancedOnChainFeatureExtractor().extract(
        {
            "question": "Will Bitcoin hit a new ATH?",
            "market_probability": 0.09,
            "model_probability": 0.18,
            "volume": 2_000_000,
            "liquidity": 100_000,
            "onchain_volume_surge": 1.5,
            "onchain_funding_rate_momentum": -0.08,
            "onchain_tvl_change_24h": -0.04,
        }
    )

    assert features["enh_onchain_asset_beta"] == 1.0
    assert features["enh_whale_flow_velocity"] > 0
    assert features["enh_panic_reversion_score"] > 0
    assert features["enh_liquidation_cascade_risk"] > 0


def test_micro_round_features_detect_short_round_edge() -> None:
    features = MicroRoundFeatureExtractor().extract(
        {
            "duration_minutes": 10,
            "yes_no_sum": 1.04,
            "spread": 0.02,
            "volume": 100_000,
            "liquidity": 20_000,
            "market_probability": 0.10,
        }
    )

    assert features["micro_is_5_15m"] == 1.0
    assert features["micro_sum_excess"] > 0.03
    assert features["micro_tail_zone_8_12c"] == 1.0
