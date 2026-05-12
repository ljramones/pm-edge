from decimal import Decimal

import pytest

from core import OrderRequest, OrderSide, Venue
from execution import PaperTradingConfig, PaperTradingEngine


@pytest.mark.asyncio
async def test_paper_engine_fills_and_updates_cash() -> None:
    engine = PaperTradingEngine(PaperTradingConfig(starting_cash=Decimal("100")))

    result = await engine.place_order(
        OrderRequest(
            venue=Venue.POLYMARKET,
            market_id="m-1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=Decimal("0.50"),
            size=Decimal("10"),
        )
    )

    assert result.status == "filled"
    assert engine.cash == Decimal("95.00")
    assert len(engine.fills) == 1


@pytest.mark.asyncio
async def test_paper_engine_enforces_order_limit() -> None:
    engine = PaperTradingEngine(
        PaperTradingConfig(starting_cash=Decimal("100"), max_order_notional=Decimal("1"))
    )

    with pytest.raises(ValueError, match="exceeds limit"):
        await engine.place_order(
            OrderRequest(
                venue=Venue.POLYMARKET,
                market_id="m-1",
                outcome="Yes",
                side=OrderSide.BUY,
                price=Decimal("0.50"),
                size=Decimal("10"),
            )
        )
