"""Kalshi resolution API client."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from .schema import FinalBookSnapshot, MarketResolutionCandidate, ResolvedMarketOutcome


class KalshiResolutionClient:
    """Fetch binary settlement outcomes from Kalshi public market data."""

    venue = "kalshi"

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
        """Fetch and parse a resolved binary Kalshi outcome.

        # TODO(v1): capture clarification rulings and contested settlement status.
        # TODO(v1): support non-binary or continuous payoff contracts.
        """

        payload = await self._get_json(f"{self.base_url}/markets/{candidate.market_id}")
        raw_market = payload.get("market")
        market_payload = raw_market if isinstance(raw_market, dict) else payload
        resolved_value = _resolved_value(market_payload)
        if resolved_value is None:
            return None
        return ResolvedMarketOutcome(
            venue=self.venue,
            market_id=candidate.market_id,
            resolution_timestamp_utc=detected_at,
            venue_resolved_at_utc=_timestamp(
                market_payload.get("settled_time")
                or market_payload.get("settlement_time")
                or market_payload.get("close_time")
            ),
            resolved_value=resolved_value,
            resolution_source="kalshi_api",
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


def _resolved_value(payload: dict[str, Any]) -> float | None:
    for key in ("expiration_value", "result", "settlement_result", "settlement_value"):
        if payload.get(key) is not None:
            return _value_resolution(payload[key])
    return None


def _value_resolution(value: Any) -> float | None:
    if isinstance(value, int | float):
        number = float(value)
        if number > 1:
            number = number / 100
        return number if 0 <= number <= 1 else None
    normalized = str(value).strip().lower()
    if normalized in {"yes", "y", "true", "1"}:
        return 1.0
    if normalized in {"no", "n", "false", "0"}:
        return 0.0
    return None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)
