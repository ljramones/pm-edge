"""On-chain feature ingestion for crypto-linked prediction markets."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from core.client import UnifiedMarket
from core.config import Settings, get_settings
from core.models import utc_now
from utils.logging import get_logger

logger = get_logger(__name__)

ASSET_KEYWORDS: dict[str, list[str]] = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ethereum", "ether"],
    "SOL": ["sol", "solana"],
    "USDC": ["usdc", "circle"],
}


class OnChainMetricSnapshot(BaseModel):
    """Normalized on-chain metrics linked to one market and asset."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    asset_symbol: str
    as_of: datetime
    whale_activity: float = Field(default=0.0, ge=0.0)
    funding_rate: float = 0.0
    funding_rate_momentum: float = 0.0
    whale_flow_score: float = 0.0
    panic_reversion_score: float = 0.0
    open_interest_change: float = 0.0
    tvl_change_24h: float = 0.0
    volume_surge: float = Field(default=0.0, ge=0.0)
    large_holder_activity: float = Field(default=0.0, ge=0.0)
    sources: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    fallback_used: bool = False


class OnChainProcessor:
    """Fetch and normalize crypto on-chain metrics with safe fallbacks."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds
        )
        self._owns_http_client = http_client is None

    async def close(self) -> None:
        """Close owned network resources."""

        if self._owns_http_client:
            await self.http_client.aclose()

    async def fetch_market_metrics(
        self,
        market: UnifiedMarket,
        *,
        as_of: datetime | None = None,
    ) -> OnChainMetricSnapshot | None:
        """Fetch metrics for crypto-linked markets, or return None for non-crypto markets."""

        asset = infer_asset_symbol(market)
        if asset is None:
            return None

        anchor = as_of or utc_now()
        raw: dict[str, Any] = {}
        sources: list[str] = []
        tvl_change = 0.0
        volume_surge = 0.0
        try:
            protocol_payload = await self._fetch_defillama_protocol(asset)
            if protocol_payload:
                raw["defillama_protocol"] = protocol_payload
                sources.append("defillama")
                tvl_change = _extract_tvl_change(protocol_payload)
                volume_surge = _extract_volume_surge(protocol_payload)
        except Exception as exc:
            logger.warning(
                "onchain_defillama_failed",
                market_id=market.market_id,
                asset_symbol=asset,
                error=str(exc),
            )

        if not sources:
            return OnChainMetricSnapshot(
                market_id=market.market_id,
                asset_symbol=asset,
                as_of=anchor,
                sources=[],
                fallback_used=True,
            )

        return OnChainMetricSnapshot(
            market_id=market.market_id,
            asset_symbol=asset,
            as_of=anchor,
            whale_activity=_bounded_positive(abs(volume_surge) * 0.25),
            funding_rate=_synthetic_funding_rate(asset, tvl_change),
            funding_rate_momentum=_synthetic_funding_momentum(asset, tvl_change),
            whale_flow_score=_bounded_positive(abs(volume_surge) * 0.4 + abs(tvl_change) * 0.2),
            panic_reversion_score=max(0.0, min(1.0, -tvl_change * 2 if tvl_change < 0 else 0.0)),
            open_interest_change=0.0,
            tvl_change_24h=tvl_change,
            volume_surge=volume_surge,
            large_holder_activity=_bounded_positive(abs(tvl_change) * 0.20),
            sources=sources,
            raw=raw,
        )

    async def _fetch_defillama_protocol(self, asset_symbol: str) -> dict[str, Any]:
        protocol = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "USDC": "circle",
        }.get(asset_symbol)
        if protocol is None:
            return {}
        response = await self.http_client.get(
            f"{self.settings.defillama_base_url.rstrip('/')}/protocol/{protocol}"
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def infer_asset_symbol(market: UnifiedMarket) -> str | None:
    """Infer a crypto asset symbol from a market title and metadata."""

    text = " ".join(
        [
            market.title,
            str(market.raw.get("category") or ""),
            str(market.raw.get("event_slug") or ""),
            str(market.raw.get("slug") or ""),
        ]
    ).lower()
    for symbol, keywords in ASSET_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords):
            return symbol
    return None


def _extract_tvl_change(payload: dict[str, Any]) -> float:
    change = payload.get("change_1d")
    if change is None:
        return 0.0
    return max(-1.0, min(1.0, float(change) / 100.0))


def _extract_volume_surge(payload: dict[str, Any]) -> float:
    current = _latest_numeric(payload.get("chainTvls"))
    historical = _latest_numeric(payload.get("tokensInUsd"))
    if current <= 0 or historical <= 0:
        return 0.0
    return max(0.0, min(5.0, (current / historical) - 1.0))


def _latest_numeric(value: Any) -> float:
    if isinstance(value, dict):
        candidates: list[float] = []
        for item in value.values():
            candidates.append(_latest_numeric(item))
        return max(candidates, default=0.0)
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict):
                for key in ("totalLiquidityUSD", "tvl", "value"):
                    if key in item:
                        return _coerce_float(item[key])
            numeric = _coerce_float(item)
            if numeric:
                return numeric
    return _coerce_float(value)


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _bounded_positive(value: float) -> float:
    return max(0.0, min(5.0, value))


def _synthetic_funding_rate(asset_symbol: str, tvl_change: float) -> float:
    base = {"BTC": 0.0002, "ETH": 0.00015, "SOL": 0.0003}.get(asset_symbol, 0.0)
    return max(-0.02, min(0.02, base + tvl_change * 0.01))


def _synthetic_funding_momentum(asset_symbol: str, tvl_change: float) -> float:
    multiplier = {"BTC": 0.8, "ETH": 1.0, "SOL": 1.3}.get(asset_symbol, 1.0)
    return max(-1.0, min(1.0, tvl_change * multiplier))
