"""Paper trading engine for Phase 0 execution validation."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, Field

from core.client import OrderRequest, OrderResult, OrderSide, Venue
from core.scanner import ArbitrageOpportunity
from utils.logging import get_logger

logger = get_logger(__name__)


class PaperTradingConfig(BaseModel):
    """Risk limits and starting capital for paper trading."""

    starting_cash: Decimal = Decimal("10000")
    max_order_notional: Decimal = Decimal("100")
    max_portfolio_notional: Decimal = Decimal("1000")


class PaperPosition(BaseModel):
    """Paper position tracked by venue, market, and outcome."""

    venue: Venue
    market_id: str
    outcome: str
    size: Decimal = Decimal("0")
    average_price: Decimal = Decimal("0")

    @property
    def notional(self) -> Decimal:
        """Return absolute notional at average entry price."""

        return abs(self.size * self.average_price)


class PaperFill(BaseModel):
    """Recorded paper fill."""

    fill_id: str = Field(default_factory=lambda: str(uuid4()))
    order_id: str
    venue: Venue
    market_id: str
    outcome: str
    side: OrderSide
    price: Decimal
    size: Decimal
    notional: Decimal


class PaperTradingEngine:
    """Deterministic in-memory paper execution with basic risk checks."""

    def __init__(self, config: PaperTradingConfig | None = None) -> None:
        self.config = config or PaperTradingConfig()
        self.cash = self.config.starting_cash
        self.positions: dict[tuple[Venue, str, str], PaperPosition] = {}
        self.fills: list[PaperFill] = []

    @property
    def portfolio_notional(self) -> Decimal:
        """Return total absolute position notional."""

        return sum((position.notional for position in self.positions.values()), Decimal("0"))

    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Validate and immediately fill a paper order."""

        notional = order.price * order.size
        self._validate_order(order, notional)
        order_id = f"paper-{uuid4()}"

        fill = PaperFill(
            order_id=order_id,
            venue=order.venue,
            market_id=order.market_id,
            outcome=order.outcome,
            side=order.side,
            price=order.price,
            size=order.size,
            notional=notional,
        )
        self._apply_fill(fill)
        self.fills.append(fill)
        logger.info(
            "paper_order_filled",
            order_id=order_id,
            venue=order.venue.value,
            market_id=order.market_id,
            outcome=order.outcome,
            side=order.side.value,
            price=str(order.price),
            size=str(order.size),
            notional=str(notional),
            cash=str(self.cash),
        )
        return OrderResult(
            venue=order.venue,
            order_id=order_id,
            status="filled",
            raw=fill.model_dump(mode="json"),
        )

    async def execute_arbitrage(
        self,
        opportunity: ArbitrageOpportunity,
        *,
        size: Decimal | None = None,
    ) -> list[OrderResult]:
        """Paper execute both legs of an arbitrage opportunity."""

        target_size = size or opportunity.max_size or Decimal("1")
        buy = OrderRequest(
            venue=opportunity.buy_venue,
            market_id=opportunity.buy_market_id,
            outcome=opportunity.outcome,
            side=OrderSide.BUY,
            price=opportunity.buy_price,
            size=target_size,
        )
        sell = OrderRequest(
            venue=opportunity.sell_venue,
            market_id=opportunity.sell_market_id,
            outcome=opportunity.outcome,
            side=OrderSide.SELL,
            price=opportunity.sell_price,
            size=target_size,
        )
        return [await self.place_order(buy), await self.place_order(sell)]

    def _validate_order(self, order: OrderRequest, notional: Decimal) -> None:
        if order.size <= 0:
            raise ValueError("Order size must be positive.")
        if order.price <= 0 or order.price >= 1:
            raise ValueError("Prediction market order price must be between 0 and 1.")
        if notional > self.config.max_order_notional:
            raise ValueError(
                f"Order notional {notional} exceeds limit {self.config.max_order_notional}."
            )
        projected_notional = self.portfolio_notional + notional
        if projected_notional > self.config.max_portfolio_notional:
            raise ValueError(
                "Projected portfolio notional "
                f"{projected_notional} exceeds limit {self.config.max_portfolio_notional}."
            )
        if order.side == OrderSide.BUY and notional > self.cash:
            raise ValueError("Insufficient paper cash for buy order.")

    def _apply_fill(self, fill: PaperFill) -> None:
        key = (fill.venue, fill.market_id, fill.outcome)
        position = self.positions.get(
            key,
            PaperPosition(venue=fill.venue, market_id=fill.market_id, outcome=fill.outcome),
        )

        signed_size = fill.size if fill.side == OrderSide.BUY else -fill.size
        new_size = position.size + signed_size
        if fill.side == OrderSide.BUY:
            self.cash -= fill.notional
        else:
            self.cash += fill.notional

        if new_size == 0:
            self.positions.pop(key, None)
            return

        if position.size == 0 or (position.size > 0) == (signed_size > 0):
            weighted_cost = (position.average_price * abs(position.size)) + fill.notional
            average_price = weighted_cost / abs(new_size)
        else:
            average_price = position.average_price

        self.positions[key] = PaperPosition(
            venue=fill.venue,
            market_id=fill.market_id,
            outcome=fill.outcome,
            size=new_size,
            average_price=average_price,
        )
