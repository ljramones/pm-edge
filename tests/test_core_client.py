from decimal import Decimal

from core import OrderRequest, OrderSide, Venue


def test_order_request_uses_normalized_side() -> None:
    order = OrderRequest(
        venue=Venue.POLYMARKET,
        market_id="market-1",
        outcome="Yes",
        side=OrderSide.BUY,
        price=Decimal("0.52"),
        size=Decimal("10"),
    )

    assert order.side.value == "buy"
    assert order.venue.value == "polymarket"
