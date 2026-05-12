from decimal import Decimal

import pytest

from core import OrderBook, UnifiedMarket, Venue
from features import FeatureStore
from strategies import EdgeDetector


@pytest.mark.asyncio
async def test_edge_detector_returns_edge_signal() -> None:
    market = UnifiedMarket(
        venue=Venue.POLYMARKET,
        market_id="m-1",
        title="Will event happen?",
        outcomes=["Yes", "No"],
    )
    detector = EdgeDetector(FeatureStore())

    signal = await detector.score_market(
        market,
        model_context={
            "order_book": OrderBook(
                market_id="m-1",
                bids=[(Decimal("0.40"), Decimal("10"))],
                asks=[(Decimal("0.42"), Decimal("12"))],
            )
        },
    )

    assert signal.market_id == "m-1"
    assert 0 <= signal.confidence <= 1
    assert signal.edge == pytest.approx(signal.model_prob - signal.market_prob)
