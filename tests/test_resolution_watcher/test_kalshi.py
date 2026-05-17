from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from data.resolution_watcher.kalshi import KalshiResolutionClient, _resolved_value
from data.resolution_watcher.schema import FinalBookSnapshot, MarketResolutionCandidate


@pytest.mark.asyncio
async def test_kalshi_fetches_binary_resolution() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trade-api/v2/markets/KTEST-YES"
        return httpx.Response(
            200,
            json={
                "market": {
                    "ticker": "KTEST-YES",
                    "status": "settled",
                    "result": "no",
                    "settled_time": "2026-05-16T12:00:00Z",
                }
            },
        )

    client = KalshiResolutionClient(
        base_url="https://external-api.kalshi.com/trade-api/v2",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    candidate = MarketResolutionCandidate(
        venue="kalshi",
        market_id="KTEST-YES",
        captured_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
        end_date=None,
        status="settled",
    )

    outcome = await client.fetch_resolution_outcome(
        candidate,
        detected_at=datetime(2026, 5, 16, 12, 1, tzinfo=UTC),
        final_snapshot=FinalBookSnapshot(0.0, 0.01, 0.01, None),
    )

    assert outcome is not None
    assert outcome.resolved_value == 0.0
    assert outcome.resolution_source == "kalshi_api"
    assert outcome.final_top_ask == 0.01
    await client.close()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "ticker": "KXMVECROSSCATEGORY",
                "status": "finalized",
                "result": "yes",
                "expiration_value": "",
                "settlement_value_dollars": "1.0000",
            },
            1.0,
        ),
        (
            {
                "ticker": "KXXRP-26MAY1709-B1.6099500",
                "status": "finalized",
                "result": "no",
                "expiration_value": "1.4231",
                "settlement_value_dollars": "0.0000",
            },
            0.0,
        ),
        (
            {
                "ticker": "KXEUROVISIONRANK-26TOP10-AUS",
                "status": "finalized",
                "expiration_value": "Yes",
            },
            1.0,
        ),
        ({"status": "active", "result": "", "expiration_value": ""}, None),
        ({"status": "finalized", "result": "YES"}, 1.0),
        ({"status": "finalized", "result": "", "expiration_value": "No"}, 0.0),
        ({"status": "finalized", "settlement_value_dollars": "1.0000"}, 1.0),
    ],
)
def test_kalshi_resolved_value_uses_authoritative_fields_before_expiration_value(
    payload: dict[str, str],
    expected: float | None,
) -> None:
    assert _resolved_value(payload) == expected
