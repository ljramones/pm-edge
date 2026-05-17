"""Polymarket resolution API client."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from utils.logging import get_logger

from .schema import FinalBookSnapshot, MarketResolutionCandidate, ResolvedMarketOutcome


class PolymarketResolutionClient:
    """Fetch binary resolution outcomes from Polymarket public REST data."""

    venue = "polymarket"

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: int = 20,
        retry_attempts: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self.retry_attempts = retry_attempts
        self._owns_client = client is None
        self._logger = get_logger(__name__)

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def fetch_resolution_outcome(
        self,
        candidate: MarketResolutionCandidate,
        *,
        detected_at: datetime,
        final_snapshot: FinalBookSnapshot,
    ) -> ResolvedMarketOutcome | None:
        """Fetch and parse a resolved binary Polymarket outcome.

        # TODO(v1): capture UMA dispute status and resolution changes.
        # TODO(v1): support multi-outcome and fractional payout markets.
        """

        condition_id = str(candidate.raw_payload().get("conditionId") or candidate.market_id)
        payload = await self._get_json(f"{self.base_url}/markets/{condition_id}")
        resolved_value = _resolved_value(payload)
        if resolved_value is None:
            return None
        venue_resolved_at = await self._fetch_venue_resolved_at(condition_id)
        return ResolvedMarketOutcome(
            venue=self.venue,
            market_id=candidate.market_id,
            resolution_timestamp_utc=detected_at,
            venue_resolved_at_utc=venue_resolved_at,
            resolved_value=resolved_value,
            resolution_source="polymarket_api",
            final_top_bid=final_snapshot.top_bid,
            final_top_ask=final_snapshot.top_ask,
            final_spread=final_snapshot.spread,
            final_snapshot_timestamp_utc=final_snapshot.timestamp_utc,
            metadata_snapshot_id=candidate.metadata_snapshot_id,
        )

    async def _get_json(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for _attempt in range(self.retry_attempts):
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return {}

    async def _fetch_venue_resolved_at(self, market_id: str) -> datetime | None:
        """Fetch the UMA resolution timestamp from Polymarket Gamma.

        Gamma is best-effort here. If the call fails or lacks resolved UMA
        fields, resolution capture continues with a null venue timestamp.
        """

        try:
            response = await self.client.get(
                "https://gamma-api.polymarket.com/markets",
                params={"condition_ids": market_id, "closed": "true"},
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                return None
            market = payload[0]
            if not isinstance(market, dict):
                return None
            if str(market.get("umaResolutionStatus", "")).lower() != "resolved":
                return None
            return _timestamp(market.get("umaEndDate") or market.get("closedTime"))
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
            self._logger.warning(
                "polymarket_gamma_resolution_timestamp_fetch_failed",
                market_id=market_id,
                error=str(exc),
            )
            return None


def _resolved_value(payload: dict[str, Any]) -> float | None:
    token_resolution = _token_winner_resolution(payload)
    if token_resolution is not None:
        return token_resolution
    for key in ("resolvedValue", "resolutionValue", "settlementValue"):
        if payload.get(key) is not None:
            return _numeric_resolution(payload[key])
    for key in ("winningOutcome", "resolvedOutcome", "winner", "outcome"):
        if payload.get(key) is not None:
            return _string_resolution(str(payload[key]))
    if payload.get("winningOutcomeIndex") is not None:
        return 1.0 if int(payload["winningOutcomeIndex"]) == 0 else 0.0
    prices = payload.get("outcomePrices")
    if isinstance(prices, list) and len(prices) >= 2:
        first = float(prices[0])
        second = float(prices[1])
        if first == 1.0 and second == 0.0:
            return 1.0
        if first == 0.0 and second == 1.0:
            return 0.0
    return None


def _token_winner_resolution(payload: dict[str, Any]) -> float | None:
    if payload.get("closed") is not True:
        return None
    if payload.get("is_50_50_outcome") is True:
        return 0.5
    tokens = payload.get("tokens")
    if not isinstance(tokens, list):
        return None
    winners = [
        index
        for index, token in enumerate(tokens)
        if isinstance(token, dict) and token.get("winner") is True
    ]
    if len(winners) != 1:
        return None
    return 1.0 if winners[0] == 0 else 0.0


def _numeric_resolution(value: Any) -> float | None:
    number = float(value)
    if number > 1:
        number = number / 100
    if number in {0.0, 1.0}:
        return number
    return number if 0 <= number <= 1 else None


def _string_resolution(value: str) -> float | None:
    normalized = value.strip().lower()
    if normalized in {"yes", "true", "1", "long"}:
        return 1.0
    if normalized in {"no", "false", "0", "short"}:
        return 0.0
    return None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "+00" in text and "+00:" not in text:
        text = text.replace("+00", "+00:00")
    return datetime.fromisoformat(text)
