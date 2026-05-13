from decimal import Decimal

import pytest

from core import OrderRequest, OrderSide, PredictionMarketClient, Venue


class FailingBackend:
    async def fetch_markets(self, venues: list[str]) -> list[dict[str, object]]:
        raise RuntimeError("backend down")


class MockVenueBackend:
    async def fetch_markets(self) -> list[dict[str, object]]:
        return [
            {
                "id": "m-1",
                "question": "Will it rain tomorrow?",
                "outcomes": ["Yes", "No"],
                "venue": "polymarket",
            }
        ]

    async def get_order_book(self, market_id: str) -> dict[str, object]:
        return {
            "bids": [{"price": "0.50", "size": "100"}],
            "asks": [{"price": "0.52", "size": "75"}],
        }

    async def create_order(self, payload: dict[str, object]) -> dict[str, object]:
        return {"id": "order-1", "status": "submitted", **payload}


class EnvelopeVenueBackend:
    async def fetch_markets(self) -> dict[str, object]:
        return {
            "count": 1,
            "next_cursor": "LTE=",
            "data": [
                {
                    "condition_id": "condition-envelope",
                    "question": "Will this envelope parse?",
                    "tokens": [
                        {"token_id": "token-envelope-yes", "outcome": "Yes"},
                        {"token_id": "token-envelope-no", "outcome": "No"},
                    ],
                    "active": True,
                    "closed": False,
                    "archived": False,
                    "accepting_orders": True,
                    "enable_order_book": True,
                }
            ],
        }


@pytest.mark.asyncio
async def test_client_falls_back_from_pmxt_to_direct_backend() -> None:
    client = PredictionMarketClient(
        pmxt_client=FailingBackend(),
        polymarket_client=MockVenueBackend(),
    )

    markets = await client.fetch_markets([Venue.POLYMARKET])

    assert markets[0].market_id == "m-1"
    assert markets[0].venue == Venue.POLYMARKET


@pytest.mark.asyncio
async def test_client_unwraps_market_response_envelopes() -> None:
    client = PredictionMarketClient(polymarket_client=EnvelopeVenueBackend())

    markets = await client.fetch_markets([Venue.POLYMARKET])

    assert len(markets) == 1
    assert markets[0].market_id == "token-envelope-yes"
    assert markets[0].title == "Will this envelope parse?"
    assert markets[0].outcomes == ["Yes", "No"]


@pytest.mark.asyncio
async def test_client_filters_closed_clob_markets() -> None:
    class ClosedVenueBackend:
        async def fetch_markets(self) -> dict[str, object]:
            return {
                "data": [
                    {
                        "condition_id": "closed-condition",
                        "question": "Old closed market",
                        "tokens": [{"token_id": "closed-token", "outcome": "Yes"}],
                        "closed": True,
                    }
                ]
            }

    client = PredictionMarketClient(polymarket_client=ClosedVenueBackend())

    with pytest.raises(Exception, match="No prediction market backend returned markets"):
        await client.fetch_markets([Venue.POLYMARKET])


@pytest.mark.asyncio
async def test_client_normalizes_order_books_and_orders() -> None:
    client = PredictionMarketClient(polymarket_client=MockVenueBackend())

    order_book = await client.fetch_order_book("m-1", Venue.POLYMARKET)
    result = await client.place_order(
        OrderRequest(
            venue=Venue.POLYMARKET,
            market_id="m-1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=Decimal("0.52"),
            size=Decimal("10"),
        )
    )

    assert order_book.asks[0] == (Decimal("0.52"), Decimal("75"))
    assert result.order_id == "order-1"
