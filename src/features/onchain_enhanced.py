"""Enhanced deterministic on-chain and crypto-flow feature engineering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

ASSET_PATTERNS: dict[str, tuple[str, ...]] = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ethereum", "ether"),
    "SOL": ("sol", "solana"),
    "USDC": ("usdc", "circle"),
}


@dataclass(frozen=True)
class EnhancedOnChainFeatureExtractor:
    """Build crypto flow features from available market/on-chain proxies."""

    def extract(self, row: dict[str, Any]) -> dict[str, float]:
        """Return stable numeric enhanced on-chain features."""

        volume = _num(row.get("volume"))
        liquidity = _num(row.get("liquidity"), row.get("top_book_liquidity"))
        market_probability = _bounded(
            _num(row.get("market_probability"), default=0.5), 0.001, 0.999
        )
        model_probability = _bounded(_num(row.get("model_probability"), default=0.5), 0.001, 0.999)
        funding = _num(row.get("onchain_funding_rate"), row.get("funding_rate"))
        funding_momentum = _num(
            row.get("onchain_funding_rate_momentum"), row.get("funding_rate_momentum")
        )
        open_interest = _num(
            row.get("onchain_open_interest_change"), row.get("open_interest_change")
        )
        tvl_delta = _num(row.get("onchain_tvl_change_24h"), row.get("tvl_change_24h"))
        volume_surge = _num(row.get("onchain_volume_surge"), row.get("volume_surge"))
        whale = _num(
            row.get("onchain_whale_activity"),
            row.get("whale_activity"),
            row.get("large_holder_activity"),
        )

        volume_liquidity_ratio = volume / max(liquidity, 1.0) if liquidity else volume / 1_000_000
        asset = infer_asset_from_text(row)
        asset_beta = (
            {"BTC": 1.0, "ETH": 1.15, "SOL": 1.45, "USDC": 0.35}[asset]
            if asset is not None
            else 0.75
        )
        tail_pressure = max(0.0, 0.15 - market_probability) / 0.15
        model_dislocation = model_probability - market_probability
        whale_flow_velocity = _bounded(
            math.log1p(max(volume, 0.0)) / 18.0
            + whale * 0.15
            + volume_surge * 0.12
            + tail_pressure * 0.20,
            0.0,
            5.0,
        )
        smart_money_cluster_score = _bounded(
            whale_flow_velocity * 0.35
            + abs(funding_momentum) * 1.5
            + abs(open_interest) * 0.35
            + asset_beta * 0.08,
            0.0,
            5.0,
        )
        basis_pressure = _bounded(
            funding * 50.0 + funding_momentum * 2.0 + model_dislocation * 0.5,
            -5.0,
            5.0,
        )
        liquidation_cascade_risk = _bounded(
            abs(open_interest) * 0.4
            + max(volume_surge, 0.0) * 0.25
            + abs(funding_momentum) * 2.0
            + tail_pressure * 0.25,
            0.0,
            5.0,
        )
        panic_reversion = _bounded(
            max(0.0, -tvl_delta) * 2.0 + tail_pressure * 0.35 + max(0.0, -basis_pressure) * 0.15,
            0.0,
            5.0,
        )
        return {
            "enh_onchain_asset_beta": asset_beta,
            "enh_whale_flow_velocity": whale_flow_velocity,
            "enh_smart_money_cluster_score": smart_money_cluster_score,
            "enh_funding_rate_momentum": funding_momentum,
            "enh_basis_pressure": basis_pressure,
            "enh_open_interest_surge": open_interest,
            "enh_liquidation_cascade_risk": liquidation_cascade_risk,
            "enh_tvl_delta": tvl_delta,
            "enh_volume_delta": volume_surge,
            "enh_address_cluster_activity": smart_money_cluster_score * 0.5 + whale * 0.2,
            "enh_panic_reversion_score": panic_reversion,
            "enh_volume_liquidity_ratio": _bounded(volume_liquidity_ratio, 0.0, 25.0),
        }


def infer_asset_from_text(row: dict[str, Any]) -> str | None:
    """Infer asset symbol from market metadata text."""

    text = " ".join(
        str(row.get(key) or "") for key in ("question", "title", "slug", "category", "event_slug")
    ).lower()
    for symbol, patterns in ASSET_PATTERNS.items():
        if any(re.search(rf"\b{re.escape(pattern)}\b", text) for pattern in patterns):
            return symbol
    return None


def _num(*values: Any, default: float = 0.0) -> float:
    for value in values:
        if value is None:
            continue
        try:
            if value != value:
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
