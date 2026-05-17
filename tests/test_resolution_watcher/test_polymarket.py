from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from data.resolution_watcher.polymarket import PolymarketResolutionClient
from data.resolution_watcher.schema import (
    FinalBookSnapshot,
    MarketResolutionCandidate,
    ResolvedMarketOutcome,
)


@pytest.mark.asyncio
async def test_polymarket_fetches_binary_resolution() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/markets/poly-1"
        return httpx.Response(
            200,
            json={
                "winningOutcome": "YES",
                "resolutionTime": "2026-05-16T12:00:00Z",
            },
        )

    client = PolymarketResolutionClient(
        base_url="https://clob.polymarket.com",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    candidate = MarketResolutionCandidate(
        venue="polymarket",
        market_id="poly-1",
        captured_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
        end_date=None,
        status="closed",
        raw_json=json.dumps({"conditionId": "poly-1"}),
    )

    outcome = await client.fetch_resolution_outcome(
        candidate,
        detected_at=datetime(2026, 5, 16, 12, 1, tzinfo=UTC),
        final_snapshot=FinalBookSnapshot(0.99, 1.0, 0.01, None),
    )

    assert outcome is not None
    assert outcome.resolved_value == 1.0
    assert outcome.resolution_source == "polymarket_api"
    assert outcome.final_top_bid == 0.99
    await client.close()


@pytest.mark.asyncio
async def test_polymarket_tokens_first_winner_resolves_yes() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "active": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Toronto Blue Jays", "winner": True},
                {"token_id": "no-token", "outcome": "Detroit Tigers", "winner": False},
            ],
        }
    )

    assert outcome is not None
    assert outcome.resolved_value == 1.0


@pytest.mark.asyncio
async def test_polymarket_tokens_second_winner_resolves_no() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Toronto Blue Jays", "winner": False},
                {"token_id": "no-token", "outcome": "Detroit Tigers", "winner": True},
            ],
        }
    )

    assert outcome is not None
    assert outcome.resolved_value == 0.0


@pytest.mark.asyncio
async def test_polymarket_tokens_50_50_resolves_half() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "is_50_50_outcome": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": False},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        }
    )

    assert outcome is not None
    assert outcome.resolved_value == 0.5


@pytest.mark.asyncio
async def test_polymarket_closed_without_token_winner_returns_none() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": False},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        }
    )

    assert outcome is None


async def _fetch_polymarket_payload(
    payload: dict[str, object],
) -> ResolvedMarketOutcome | None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/markets/poly-1"
        return httpx.Response(200, json=payload)

    client = PolymarketResolutionClient(
        base_url="https://clob.polymarket.com",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    candidate = MarketResolutionCandidate(
        venue="polymarket",
        market_id="poly-1",
        captured_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
        end_date=None,
        status="closed",
        raw_json=json.dumps({"conditionId": "poly-1"}),
    )
    try:
        return await client.fetch_resolution_outcome(
            candidate,
            detected_at=datetime(2026, 5, 16, 12, 1, tzinfo=UTC),
            final_snapshot=FinalBookSnapshot(0.99, 1.0, 0.01, None),
        )
    finally:
        await client.close()
