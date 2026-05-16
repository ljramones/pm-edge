from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from data.resolution_watcher.polymarket import PolymarketResolutionClient
from data.resolution_watcher.schema import FinalBookSnapshot, MarketResolutionCandidate


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
