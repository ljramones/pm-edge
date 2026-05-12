"""Liquidity providing and market-making strategy primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict


class LiquidityOpportunity(BaseModel):
    """Market-making opportunity with quote guidance."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    fair_probability: float
    bid: float
    ask: float
    spread: float
    incentive_score: float
    adverse_selection_score: float
    edge: float
    post_fee_edge: float
    max_notional: float
    should_quote: bool
    reason: str
    opportunity_type: str = "maker_quote"
    link: str | None = None


@dataclass(frozen=True)
class LiquidityProviderConfig:
    """Rules and risk controls for quoting."""

    min_spread: float = 0.03
    min_incentive_score: float = 0.0
    max_adverse_selection: float = 0.45
    quote_width: float = 0.01
    max_notional: float = 50.0
    min_liquidity: float = 1_000.0
    min_post_fee_edge: float = 0.05
    maker_fee_bps: float = 0.0
    adverse_selection_buffer: float = 0.20
    tail_no_min_price: float = 0.88
    tail_no_max_price: float = 0.98
    both_sides_sum_threshold: float = 1.02


class LiquidityProvider:
    """Light model for short-duration and incentive-heavy market making."""

    def __init__(self, config: LiquidityProviderConfig | None = None) -> None:
        self.config = config or LiquidityProviderConfig()

    def evaluate(self, row: dict[str, Any]) -> LiquidityOpportunity:
        """Evaluate one market snapshot and return quote guidance."""

        market_probability = float(row.get("market_probability", row.get("mid", 0.5)) or 0.5)
        model_probability = float(
            row.get("model_probability", market_probability) or market_probability
        )
        spread = float(
            row.get("spread", abs(float(row.get("best_ask", 0)) - float(row.get("best_bid", 0))))
            or 0.0
        )
        liquidity = float(row.get("liquidity", row.get("top_book_liquidity", 0.0)) or 0.0)
        volume = float(row.get("volume", 0.0) or 0.0)
        incentive = incentive_score(row, spread=spread, liquidity=liquidity, volume=volume)
        adverse = adverse_selection_score(row)
        fair = max(0.01, min(0.99, model_probability))
        opportunity_type = classify_opportunity(
            row, market_probability=market_probability, spread=spread
        )
        bid = max(0.01, min(0.98, fair - self.config.quote_width))
        ask = max(0.02, min(0.99, fair + self.config.quote_width))
        edge = (
            abs(model_probability - market_probability)
            + spread * 0.5
            + incentive * 0.01
            - adverse * 0.02
        )
        if opportunity_type == "biased_tail_no":
            no_price = 1 - market_probability
            fair_no = 1 - fair
            edge = max(edge, no_price - fair_no)
            bid = max(0.01, min(0.98, fair_no - self.config.quote_width))
            ask = max(0.02, min(0.99, no_price))
        elif opportunity_type == "both_sides_micro_round":
            edge = max(edge, float(row.get("yes_no_sum", 1.0)) - 1.0)
        post_fee_edge = post_fee_liquidity_edge(
            edge=edge,
            spread=spread,
            adverse=adverse,
            maker_fee_bps=self.config.maker_fee_bps,
            adverse_selection_buffer=self.config.adverse_selection_buffer,
        )
        should_quote = (
            spread >= self.config.min_spread
            and incentive >= self.config.min_incentive_score
            and adverse <= self.config.max_adverse_selection
            and liquidity >= self.config.min_liquidity
            and post_fee_edge >= self.config.min_post_fee_edge
        )
        return LiquidityOpportunity(
            market_id=str(row.get("market_id")),
            fair_probability=fair,
            bid=bid,
            ask=ask,
            spread=spread,
            incentive_score=incentive,
            adverse_selection_score=adverse,
            edge=edge,
            post_fee_edge=post_fee_edge,
            max_notional=min(self.config.max_notional, max(liquidity * 0.01, 1.0)),
            should_quote=should_quote,
            reason=quote_reason(
                should_quote,
                spread=spread,
                incentive=incentive,
                adverse=adverse,
                post_fee_edge=post_fee_edge,
            ),
            opportunity_type=opportunity_type,
            link=str(row.get("url")) if row.get("url") else None,
        )

    def evaluate_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Evaluate many market snapshots."""

        return pd.DataFrame(
            [self.evaluate(row).model_dump(mode="json") for row in frame.to_dict(orient="records")]
        )


def incentive_score(
    row: dict[str, Any], *, spread: float, liquidity: float, volume: float
) -> float:
    """Score incentive attractiveness from spread, rewards, and market activity."""

    reward = float(row.get("incentive", row.get("rewards", 0.0)) or 0.0)
    duration_hours = max(float(row.get("duration_hours", 24.0) or 24.0), 1.0)
    activity = min(volume / max(liquidity, 1.0), 5.0)
    return spread * 20 + reward / duration_hours + activity * 0.1


def adverse_selection_score(row: dict[str, Any]) -> float:
    """Estimate adverse-selection risk from volatility, edge disagreement, and news velocity."""

    volatility = abs(float(row.get("price_change_1h", row.get("volatility", 0.0)) or 0.0))
    news_velocity = float(row.get("news_velocity_6h", 0.0) or 0.0)
    uncertainty = float(row.get("llm_uncertainty", 0.5) or 0.5)
    edge_abs = abs(
        float(row.get("model_probability", 0.5)) - float(row.get("market_probability", 0.5))
    )
    return max(0.0, min(1.0, volatility * 2 + news_velocity * 0.02 + uncertainty * 0.2 + edge_abs))


def classify_opportunity(row: dict[str, Any], *, market_probability: float, spread: float) -> str:
    """Classify the liquidity setup."""

    no_price = 1 - market_probability
    yes_no_sum = float(row.get("yes_no_sum", 1.0) or 1.0)
    duration = float(row.get("duration_minutes", row.get("duration_hours", 999.0) * 60) or 999.0)
    if 0.88 <= no_price <= 0.98:
        return "biased_tail_no"
    if duration <= 15 and yes_no_sum >= 1.02 and spread >= 0.01:
        return "both_sides_micro_round"
    return "maker_quote"


def post_fee_liquidity_edge(
    *,
    edge: float,
    spread: float,
    adverse: float,
    maker_fee_bps: float,
    adverse_selection_buffer: float,
) -> float:
    """Return edge after fees, spread impact, and adverse-selection haircut."""

    fee = maker_fee_bps / 10_000
    adverse_haircut = adverse * adverse_selection_buffer
    return max(0.0, edge + spread * 0.25 - fee - adverse_haircut)


def quote_reason(
    should_quote: bool, *, spread: float, incentive: float, adverse: float, post_fee_edge: float
) -> str:
    """Human-readable quote decision reason."""

    if should_quote:
        return "quote: post-fee edge clears adverse-selection haircut"
    return (
        f"skip: spread={spread:.3f}, incentive={incentive:.3f}, adverse={adverse:.3f}, "
        f"post_fee_edge={post_fee_edge:.3f}"
    )


def backtest_liquidity(
    frame: pd.DataFrame, provider: LiquidityProvider | None = None
) -> pd.DataFrame:
    """Backtest simple liquidity-providing fills from historical signal rows."""

    lp = provider or LiquidityProvider()
    opportunities = lp.evaluate_frame(frame)
    if opportunities.empty:
        return opportunities
    merged = opportunities.merge(frame[["market_id", "outcome"]], on="market_id", how="left")
    merged["expected_capture"] = merged["post_fee_edge"] * merged["max_notional"]
    merged["adverse_loss"] = merged["adverse_selection_score"] * merged["max_notional"] * 0.2
    merged["pnl"] = merged["expected_capture"] - merged["adverse_loss"]
    merged.loc[~merged["should_quote"], "pnl"] = 0.0
    return merged
