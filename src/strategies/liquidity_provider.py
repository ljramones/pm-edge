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
    quote_side: str = "both"
    maker_taker: str = "maker"
    cluster_id: str = "default"
    fear_sizing_multiplier: float = 1.0
    market_temperature: float = 0.0
    link: str | None = None
    reason_code: str = "unknown"


@dataclass(frozen=True)
class LiquidityProviderConfig:
    """Rules and risk controls for quoting."""

    min_spread: float = 0.05
    min_incentive_score: float = 0.0
    max_adverse_selection: float = 0.42
    hard_block_adverse_selection: float = 0.55
    quote_width: float = 0.01
    max_notional: float = 50.0
    starting_capital: float = 10_000.0
    min_liquidity: float = 2_500.0
    volume_liquidity_proxy: float = 0.005
    min_post_fee_edge: float = 0.08
    maker_fee_bps: float = 0.0
    maker_rebate_bps: float = 0.0
    adverse_selection_buffer: float = 0.25
    tail_no_min_price: float = 0.88
    tail_no_max_price: float = 0.92
    min_tail_post_fee_edge: float = 0.10
    max_tail_exposure: float = 0.06
    both_sides_sum_threshold: float = 1.015
    both_sides_buffer: float = 0.003
    min_micro_post_fee_edge: float = 0.06
    max_spread_for_edge: float = 0.20
    max_cluster_exposure: float = 0.08
    min_fear_sizing_multiplier: float = 0.95
    min_market_temperature: float = 0.0
    allow_generic_maker: bool = False
    min_generic_incentive_score: float = 2.0


class LiquidityProvider:
    """Conservative liquidity harvester for biased tails and crypto micro-rounds."""

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
        spread_for_edge = max(0.0, min(spread, self.config.max_spread_for_edge))
        raw_liquidity = float(row.get("liquidity", row.get("top_book_liquidity", 0.0)) or 0.0)
        volume = float(row.get("volume", 0.0) or 0.0)
        liquidity = max(raw_liquidity, volume * self.config.volume_liquidity_proxy)
        incentive = incentive_score(row, spread=spread_for_edge, liquidity=liquidity, volume=volume)
        scored_row = {**row, "effective_liquidity": liquidity}
        adverse = adverse_selection_score(scored_row)
        fair = max(0.01, min(0.99, model_probability))
        opportunity_type = classify_opportunity(
            row,
            market_probability=market_probability,
            spread=spread_for_edge,
            config=self.config,
        )
        fear_multiplier = float(row.get("fear_sizing_multiplier", 1.0) or 1.0)
        market_temperature = float(row.get("market_temperature", 0.0) or 0.0)
        cluster_id = str(
            row.get("event_cluster")
            or row.get("category")
            or row.get("slug")
            or row.get("market_id")
            or "default"
        )
        bid = max(0.01, min(0.98, fair - self.config.quote_width))
        ask = max(0.02, min(0.99, fair + self.config.quote_width))
        edge = (
            abs(model_probability - market_probability)
            + spread_for_edge * 0.5
            + incentive * 0.01
            - adverse * 0.02
        )
        quote_side = "both"
        if opportunity_type == "biased_tail_no":
            no_price = 1 - market_probability
            fair_no = 1 - fair
            edge = max(edge, no_price - fair_no)
            bid = max(0.01, min(0.98, fair_no - self.config.quote_width))
            ask = max(0.02, min(0.99, no_price))
            quote_side = "sell_no"
        elif opportunity_type == "both_sides_micro_round":
            edge = max(edge, float(row.get("yes_no_sum", 1.0)) - 1.0)
            quote_side = "both"
        post_fee_edge = post_fee_liquidity_edge(
            edge=edge,
            spread=spread_for_edge,
            adverse=adverse,
            maker_fee_bps=self.config.maker_fee_bps,
            adverse_selection_buffer=self.config.adverse_selection_buffer,
        )
        decision = quote_decision(
            opportunity_type=opportunity_type,
            spread=spread,
            incentive=incentive,
            adverse=adverse,
            liquidity=liquidity,
            post_fee_edge=post_fee_edge,
            fear_multiplier=fear_multiplier,
            market_temperature=market_temperature,
            config=self.config,
        )
        should_quote = decision.should_quote
        cluster_cap = self.config.starting_capital * self.config.max_cluster_exposure
        if opportunity_type == "biased_tail_no":
            cluster_cap = min(
                cluster_cap, self.config.starting_capital * self.config.max_tail_exposure
            )
        liquidity_cap = max(liquidity * 0.01, 1.0)
        fear_adjusted_cap = self.config.max_notional * max(min(fear_multiplier, 1.25), 0.0)
        return LiquidityOpportunity(
            market_id=str(row.get("market_id")),
            fair_probability=fair,
            bid=bid,
            ask=ask,
            spread=spread_for_edge,
            incentive_score=incentive,
            adverse_selection_score=adverse,
            edge=edge,
            post_fee_edge=post_fee_edge,
            max_notional=min(fear_adjusted_cap, liquidity_cap, cluster_cap),
            should_quote=should_quote,
            reason=decision.reason,
            opportunity_type=opportunity_type,
            quote_side=quote_side,
            maker_taker="maker",
            cluster_id=cluster_id,
            fear_sizing_multiplier=fear_multiplier,
            market_temperature=market_temperature,
            link=str(row.get("url")) if row.get("url") else None,
            reason_code=decision.reason_code,
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


@dataclass(frozen=True)
class QuoteDecision:
    """Quote/skip decision with a stable reason code for diagnostics."""

    should_quote: bool
    reason_code: str
    reason: str


def adverse_selection_score(row: dict[str, Any]) -> float:
    """Estimate adverse-selection risk from flow, volatility, imbalance, and news velocity."""

    volatility = abs(float(row.get("price_change_1h", row.get("volatility", 0.0)) or 0.0))
    price_change_6h = abs(float(row.get("price_change_6h", 0.0) or 0.0))
    price_change_24h = abs(float(row.get("price_change_24h", 0.0) or 0.0))
    news_velocity = float(row.get("news_velocity_6h", 0.0) or 0.0)
    uncertainty = float(row.get("llm_uncertainty", 0.5) or 0.5)
    imbalance = abs(float(row.get("order_flow_imbalance", row.get("imbalance", 0.0)) or 0.0))
    opposing_flow = float(row.get("large_opposing_flow", row.get("opposing_flow", 0.0)) or 0.0)
    whale_activity = float(
        row.get(
            "onchain_whale_activity",
            row.get("whale_activity", row.get("large_holder_activity", 0.0)),
        )
        or 0.0
    )
    funding_momentum = abs(
        float(row.get("funding_rate_momentum", row.get("funding_momentum", 0.0)) or 0.0)
    )
    open_interest_surge = float(row.get("open_interest_surge", row.get("oi_surge", 0.0)) or 0.0)
    volume_surge = float(row.get("volume_surge", row.get("volume_zscore", 0.0)) or 0.0)
    liquidity = max(
        float(
            row.get("effective_liquidity", row.get("liquidity", row.get("top_book_liquidity", 1.0)))
            or 1.0
        ),
        1.0,
    )
    volume = float(row.get("volume", 0.0) or 0.0)
    flow_pressure = min(volume / liquidity, 8.0) * 0.025
    edge_abs = abs(
        float(row.get("model_probability", 0.5)) - float(row.get("market_probability", 0.5))
    )
    return max(
        0.0,
        min(
            1.0,
            volatility * 2.5
            + price_change_6h
            + price_change_24h * 0.5
            + news_velocity * 0.02
            + uncertainty * 0.2
            + edge_abs
            + imbalance * 0.35
            + opposing_flow * 0.45
            + whale_activity * 0.20
            + funding_momentum * 2.0
            + open_interest_surge * 0.15
            + volume_surge * 0.05
            + flow_pressure,
        ),
    )


def classify_opportunity(
    row: dict[str, Any],
    *,
    market_probability: float,
    spread: float,
    config: LiquidityProviderConfig | None = None,
) -> str:
    """Classify the liquidity setup."""

    cfg = config or LiquidityProviderConfig()
    no_price = 1 - market_probability
    yes_no_sum = float(row.get("yes_no_sum", 1.0) or 1.0)
    duration = float(row.get("duration_minutes", row.get("duration_hours", 999.0) * 60) or 999.0)
    if cfg.tail_no_min_price <= no_price <= cfg.tail_no_max_price:
        return "biased_tail_no"
    if (
        duration <= 15
        and yes_no_sum >= cfg.both_sides_sum_threshold + cfg.both_sides_buffer
        and spread >= 0.01
    ):
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


def quote_decision(
    *,
    opportunity_type: str,
    spread: float,
    incentive: float,
    adverse: float,
    liquidity: float,
    post_fee_edge: float,
    fear_multiplier: float,
    market_temperature: float,
    config: LiquidityProviderConfig,
) -> QuoteDecision:
    """Return a strict quote decision with a stable reason code."""

    def skip(code: str) -> QuoteDecision:
        return QuoteDecision(
            should_quote=False,
            reason_code=code,
            reason=(
                f"skip:{code}: spread={spread:.3f}, incentive={incentive:.3f}, "
                f"adverse={adverse:.3f}, liquidity={liquidity:.0f}, "
                f"post_fee_edge={post_fee_edge:.3f}, fear={fear_multiplier:.3f}, "
                f"temperature={market_temperature:.3f}"
            ),
        )

    if adverse >= config.hard_block_adverse_selection:
        return skip("hard_adverse_block")
    if adverse > config.max_adverse_selection:
        return skip("adverse_selection")
    if fear_multiplier < config.min_fear_sizing_multiplier:
        return skip("fear_router")
    if market_temperature < config.min_market_temperature:
        return skip("temperature_router")
    if liquidity < config.min_liquidity:
        return skip("insufficient_liquidity")
    if spread < config.min_spread and opportunity_type != "both_sides_micro_round":
        return skip("spread_too_tight")
    if incentive < config.min_incentive_score:
        return skip("low_incentive")
    if opportunity_type == "biased_tail_no":
        if post_fee_edge < max(config.min_post_fee_edge, config.min_tail_post_fee_edge):
            return skip("tail_edge_below_gate")
    elif opportunity_type == "both_sides_micro_round":
        if post_fee_edge < config.min_micro_post_fee_edge:
            return skip("micro_edge_below_gate")
    elif not config.allow_generic_maker or incentive < config.min_generic_incentive_score:
        return skip("no_strategic_setup")
    elif post_fee_edge < config.min_post_fee_edge:
        return skip("edge_below_gate")

    return QuoteDecision(
        should_quote=True,
        reason_code=f"quote_{opportunity_type}",
        reason=(
            f"quote:{opportunity_type}: spread={spread:.3f}, incentive={incentive:.3f}, "
            f"adverse={adverse:.3f}, liquidity={liquidity:.0f}, "
            f"post_fee_edge={post_fee_edge:.3f}, fear={fear_multiplier:.3f}, "
            f"temperature={market_temperature:.3f}"
        ),
    )


def backtest_liquidity(
    frame: pd.DataFrame, provider: LiquidityProvider | None = None
) -> pd.DataFrame:
    """Backtest simple liquidity-providing fills from historical signal rows."""

    lp = provider or LiquidityProvider()
    source = frame.reset_index(drop=True).copy()
    source["_row_id"] = range(len(source))
    opportunities = lp.evaluate_frame(source)
    if opportunities.empty:
        return opportunities
    passthrough = [
        column
        for column in [
            "_row_id",
            "outcome",
            "as_of",
            "resolved_at",
            "category",
            "volume",
            "liquidity",
            "market_probability",
            "model_probability",
        ]
        if column in source.columns
    ]
    merged = opportunities.join(source[passthrough])
    merged["expected_capture"] = merged["post_fee_edge"] * merged["max_notional"]
    merged["incentive_capture"] = merged["incentive_score"] * merged["max_notional"] * 0.002
    merged["maker_rebate_capture"] = merged["max_notional"] * lp.config.maker_rebate_bps / 10_000
    merged["adverse_selection_loss"] = (
        merged["adverse_selection_score"]
        * merged["max_notional"]
        * lp.config.adverse_selection_buffer
    )
    merged["gross_pnl"] = merged.apply(conservative_quote_pnl, axis=1)
    merged["pnl"] = (
        merged["gross_pnl"]
        + merged["incentive_capture"]
        + merged["maker_rebate_capture"]
        - merged["adverse_selection_loss"]
    )
    merged.loc[~merged["should_quote"], "pnl"] = 0.0
    merged["stake"] = merged["max_notional"]
    merged["return_on_capital"] = merged["pnl"] / merged["stake"].clip(lower=1e-9)
    return merged


def conservative_quote_pnl(row: pd.Series) -> float:
    """Estimate realized quote PnL with capped adverse-selection loss.

    Liquidity harvesting is modeled as recycling maker quotes, not holding cheap
    lottery-like exposure to expiry. Winning quotes capture the expected spread
    economics; losing quotes pay a bounded adverse-selection cost against quote
    notional.
    """

    outcome = row.get("outcome")
    if pd.isna(outcome):
        return 0.0

    market_probability = float(row.get("market_probability", 0.5) or 0.5)
    model_probability = float(
        row.get("model_probability", market_probability) or market_probability
    )
    opportunity_type = str(row.get("opportunity_type", "maker_quote"))
    expected_capture = max(float(row.get("expected_capture", 0.0) or 0.0), 0.0)
    max_notional = max(float(row.get("max_notional", 0.0) or 0.0), 0.0)
    adverse_score = min(max(float(row.get("adverse_selection_score", 0.0) or 0.0), 0.0), 1.0)

    direction = 1 if model_probability >= market_probability else -1
    if row.get("quote_side") == "sell_no":
        direction = 1

    wins = int(outcome) == 1 if direction > 0 else int(outcome) == 0
    if wins:
        return expected_capture

    if opportunity_type == "biased_tail_no":
        loss_fraction = 0.20 + adverse_score * 0.30
    elif opportunity_type == "both_sides_micro_round":
        loss_fraction = 0.10 + adverse_score * 0.25
    else:
        loss_fraction = 0.05 + adverse_score * 0.20
    return -max_notional * min(loss_fraction, 1.0)


def liquidity_diagnostics(frame: pd.DataFrame) -> dict[str, float]:
    """Return rich liquidity-harvester diagnostics."""

    if frame.empty:
        return {
            "liquidity_quote_count": 0.0,
            "liquidity_pnl": 0.0,
            "incentive_capture_rate": 0.0,
            "adverse_selection_loss": 0.0,
            "maker_ratio": 0.0,
            "taker_ratio": 0.0,
        }
    quoted = frame[frame["should_quote"].astype(bool)] if "should_quote" in frame else frame
    quote_count = float(len(quoted))
    total = max(float(len(frame)), 1.0)
    maker_ratio = (
        float((quoted["maker_taker"] == "maker").mean())
        if quote_count and "maker_taker" in quoted
        else 0.0
    )
    diagnostics = {
        "liquidity_quote_count": quote_count,
        "liquidity_quote_rate": quote_count / total,
        "liquidity_pnl": float(quoted["pnl"].sum()) if "pnl" in quoted else 0.0,
        "liquidity_expected_capture": (
            float(quoted["expected_capture"].sum()) if "expected_capture" in quoted else 0.0
        ),
        "incentive_capture": (
            float(quoted["incentive_capture"].sum()) if "incentive_capture" in quoted else 0.0
        ),
        "incentive_capture_rate": (
            float(quoted["incentive_capture"].sum() / max(quoted["max_notional"].sum(), 1e-9))
            if quote_count and "incentive_capture" in quoted and "max_notional" in quoted
            else 0.0
        ),
        "adverse_selection_loss": (
            float(quoted["adverse_selection_loss"].sum())
            if "adverse_selection_loss" in quoted
            else 0.0
        ),
        "average_post_fee_edge": (
            float(quoted["post_fee_edge"].mean())
            if quote_count and "post_fee_edge" in quoted
            else 0.0
        ),
        "maker_ratio": maker_ratio,
        "taker_ratio": 1.0 - maker_ratio if quote_count else 0.0,
        "biased_tail_no_quotes": (
            float((quoted["opportunity_type"] == "biased_tail_no").sum())
            if quote_count and "opportunity_type" in quoted
            else 0.0
        ),
        "both_sides_micro_round_quotes": (
            float((quoted["opportunity_type"] == "both_sides_micro_round").sum())
            if quote_count and "opportunity_type" in quoted
            else 0.0
        ),
    }
    diagnostics.update(liquidity_pnl_attribution(frame))
    return diagnostics


def liquidity_pnl_attribution(frame: pd.DataFrame) -> dict[str, float]:
    """Return flattened PnL attribution for quote type, router, and reason-code slices."""

    if frame.empty or "pnl" not in frame:
        return {}
    quoted = frame[frame["should_quote"].astype(bool)] if "should_quote" in frame else frame
    if quoted.empty:
        return liquidity_rejection_diagnostics(frame)

    attribution: dict[str, float] = {}
    attribution.update(liquidity_rejection_diagnostics(frame))
    for group_col, prefix in [
        ("opportunity_type", "type"),
        ("reason_code", "reason"),
    ]:
        if group_col not in quoted:
            continue
        grouped = quoted.groupby(group_col, dropna=False)["pnl"].agg(["count", "sum", "mean"])
        for key, row in grouped.iterrows():
            safe_key = str(key).replace(" ", "_").replace(":", "_")
            attribution[f"{prefix}_{safe_key}_quotes"] = float(row["count"])
            attribution[f"{prefix}_{safe_key}_pnl"] = float(row["sum"])
            attribution[f"{prefix}_{safe_key}_mean_pnl"] = float(row["mean"])

    if "fear_sizing_multiplier" in quoted:
        high_fear = quoted["fear_sizing_multiplier"].astype(float) >= 1.0
        attribution["high_fear_quotes"] = float(high_fear.sum())
        attribution["high_fear_pnl"] = float(quoted.loc[high_fear, "pnl"].sum())
        attribution["low_fear_quotes"] = float((~high_fear).sum())
        attribution["low_fear_pnl"] = float(quoted.loc[~high_fear, "pnl"].sum())

    if "market_temperature" in quoted:
        temperatures = quoted["market_temperature"].astype(float)
        threshold = float(temperatures.median()) if len(temperatures) else 0.0
        high_temp = temperatures >= threshold
        attribution["high_temperature_threshold"] = threshold
        attribution["high_temperature_quotes"] = float(high_temp.sum())
        attribution["high_temperature_pnl"] = float(quoted.loc[high_temp, "pnl"].sum())
        attribution["low_temperature_quotes"] = float((~high_temp).sum())
        attribution["low_temperature_pnl"] = float(quoted.loc[~high_temp, "pnl"].sum())
    return attribution


def liquidity_rejection_diagnostics(frame: pd.DataFrame) -> dict[str, float]:
    """Return quote rejection counts by stable reason code."""

    if frame.empty or "should_quote" not in frame or "reason_code" not in frame:
        return {}
    rejected = frame[~frame["should_quote"].astype(bool)]
    if rejected.empty:
        return {"rejected_total": 0.0}
    counts = rejected["reason_code"].value_counts(dropna=False)
    diagnostics = {"rejected_total": float(len(rejected))}
    for reason, count in counts.items():
        diagnostics[f"rejected_{str(reason)}"] = float(count)
    return diagnostics
