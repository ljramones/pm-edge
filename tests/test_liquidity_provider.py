from __future__ import annotations

import pandas as pd

from strategies import LiquidityProvider, LiquidityProviderConfig, backtest_liquidity


def test_liquidity_provider_quotes_wide_low_risk_market() -> None:
    provider = LiquidityProvider(
        LiquidityProviderConfig(min_spread=0.03, max_adverse_selection=0.5)
    )

    opportunity = provider.evaluate(
        {
            "market_id": "m1",
            "market_probability": 0.50,
            "model_probability": 0.51,
            "spread": 0.06,
            "liquidity": 100_000,
            "volume": 50_000,
            "llm_uncertainty": 0.2,
        }
    )

    assert opportunity.should_quote is True
    assert opportunity.bid < opportunity.ask
    assert opportunity.post_fee_edge >= 0.05


def test_liquidity_provider_identifies_biased_tail_no() -> None:
    provider = LiquidityProvider(
        LiquidityProviderConfig(min_spread=0.01, max_adverse_selection=0.5)
    )

    opportunity = provider.evaluate(
        {
            "market_id": "longshot",
            "market_probability": 0.08,
            "model_probability": 0.04,
            "spread": 0.04,
            "liquidity": 50_000,
            "volume": 20_000,
            "llm_uncertainty": 0.1,
        }
    )

    assert opportunity.opportunity_type == "biased_tail_no"
    assert opportunity.should_quote is True


def test_liquidity_backtest_outputs_pnl() -> None:
    frame = pd.DataFrame(
        {
            "market_id": ["m1"],
            "market_probability": [0.50],
            "model_probability": [0.51],
            "spread": [0.06],
            "liquidity": [100_000],
            "volume": [50_000],
            "llm_uncertainty": [0.1],
            "outcome": [1],
        }
    )

    result = backtest_liquidity(frame)

    assert result["should_quote"].iloc[0]
    assert "pnl" in result
