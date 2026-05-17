from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

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
        if request.url.host == "gamma-api.polymarket.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "conditionId": "poly-1",
                        "umaResolutionStatus": "resolved",
                        "umaEndDate": "2026-05-16T12:00:00Z",
                    }
                ],
            )
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
    assert outcome.venue_resolved_at_utc == datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
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


@pytest.mark.asyncio
async def test_polymarket_gamma_timestamp_populates_venue_resolved_at() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": True},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        },
        gamma_payload=[
            {
                "conditionId": "poly-1",
                "umaResolutionStatus": "resolved",
                "umaEndDate": "2026-05-17T17:04:05Z",
                "closedTime": "2026-05-17 17:04:05+00",
            }
        ],
    )

    assert outcome is not None
    assert outcome.venue_resolved_at_utc == datetime(2026, 5, 17, 17, 4, 5, tzinfo=UTC)


@pytest.mark.asyncio
async def test_polymarket_gamma_empty_array_keeps_resolution_without_timestamp() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": True},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        },
        gamma_payload=[],
    )

    assert outcome is not None
    assert outcome.resolved_value == 1.0
    assert outcome.venue_resolved_at_utc is None


@pytest.mark.asyncio
async def test_polymarket_gamma_http_error_keeps_resolution_without_timestamp() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": True},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        },
        gamma_status_code=500,
    )

    assert outcome is not None
    assert outcome.resolved_value == 1.0
    assert outcome.venue_resolved_at_utc is None


@pytest.mark.asyncio
async def test_polymarket_gamma_unresolved_status_keeps_timestamp_null() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": True},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        },
        gamma_payload=[
            {
                "conditionId": "poly-1",
                "umaResolutionStatus": "proposed",
                "umaEndDate": "2026-05-17T17:04:05Z",
            }
        ],
    )

    assert outcome is not None
    assert outcome.venue_resolved_at_utc is None


@pytest.mark.asyncio
async def test_polymarket_gamma_closed_time_fallback_populates_timestamp() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": True},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        },
        gamma_payload=[
            {
                "conditionId": "poly-1",
                "umaResolutionStatus": "resolved",
                "closedTime": "2026-05-17 17:04:05+00",
            }
        ],
    )

    assert outcome is not None
    assert outcome.venue_resolved_at_utc == datetime(2026, 5, 17, 17, 4, 5, tzinfo=UTC)


@pytest.mark.asyncio
async def test_polymarket_gamma_missing_timestamp_fields_keeps_timestamp_null() -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": True},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        },
        gamma_payload=[
            {
                "conditionId": "poly-1",
                "umaResolutionStatus": "resolved",
            }
        ],
    )

    assert outcome is not None
    assert outcome.venue_resolved_at_utc is None


@pytest.mark.parametrize(
    ("gamma_payload", "expected"),
    [
        (
            [
                {
                    "umaResolutionStatus": "resolved",
                    "umaEndDate": "2026-05-17T17:04:05Z",
                }
            ],
            datetime(2026, 5, 17, 17, 4, 5, tzinfo=UTC),
        ),
        (
            [
                {
                    "umaResolutionStatus": "resolved",
                    "closedTime": "2026-05-17 17:04:05+00",
                }
            ],
            datetime(2026, 5, 17, 17, 4, 5, tzinfo=UTC),
        ),
    ],
)
@pytest.mark.asyncio
async def test_polymarket_gamma_date_parsing_handles_observed_formats(
    gamma_payload: list[dict[str, str]],
    expected: datetime,
) -> None:
    outcome = await _fetch_polymarket_payload(
        {
            "closed": True,
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes", "winner": True},
                {"token_id": "no-token", "outcome": "No", "winner": False},
            ],
        },
        gamma_payload=gamma_payload,
    )

    assert outcome is not None
    assert outcome.venue_resolved_at_utc == expected


async def _fetch_polymarket_payload(
    payload: dict[str, object],
    *,
    gamma_payload: Sequence[Any] | None = None,
    gamma_status_code: int = 200,
) -> ResolvedMarketOutcome | None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gamma-api.polymarket.com":
            assert request.url.params["condition_ids"] == "poly-1"
            assert request.url.params["closed"] == "true"
            return httpx.Response(gamma_status_code, json=gamma_payload or [])
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
