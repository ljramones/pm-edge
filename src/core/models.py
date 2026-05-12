"""Database models for unified prediction market state."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(tz=UTC)


class Venue(StrEnum):
    """Supported market venues."""

    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class MarketStatus(StrEnum):
    """Normalized market lifecycle state."""

    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class TradeSide(StrEnum):
    """Trade direction."""

    BUY = "buy"
    SELL = "sell"


class Market(SQLModel, table=True):
    """Unified market representation across prediction market venues."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    venue: Venue = Field(index=True)
    venue_market_id: str = Field(index=True)
    title: str
    description: str | None = None
    category: str | None = Field(default=None, index=True)
    status: MarketStatus = Field(default=MarketStatus.OPEN, index=True)
    url: str | None = None
    outcomes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    opens_at: datetime | None = None
    closes_at: datetime | None = Field(default=None, index=True)
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketPrice(SQLModel, table=True):
    """Historical market price snapshot."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    market_id: str = Field(foreign_key="market.id", index=True)
    outcome: str = Field(index=True)
    bid: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    ask: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    mid: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    last: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    volume: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    liquidity: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    observed_at: datetime = Field(default_factory=utc_now, index=True)
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))


class Resolution(SQLModel, table=True):
    """Final market outcome and resolution metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    market_id: str = Field(foreign_key="market.id", index=True)
    winning_outcome: str
    resolved_at: datetime = Field(default_factory=utc_now, index=True)
    source_url: str | None = None
    notes: str | None = None
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))


class Position(SQLModel, table=True):
    """Current or historical portfolio position."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    venue: Venue = Field(index=True)
    market_id: str = Field(foreign_key="market.id", index=True)
    outcome: str = Field(index=True)
    size: Decimal = Field(max_digits=18, decimal_places=6)
    average_price: Decimal = Field(max_digits=12, decimal_places=6)
    realized_pnl: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=6)
    unrealized_pnl: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=6)
    opened_at: datetime = Field(default_factory=utc_now, index=True)
    closed_at: datetime | None = Field(default=None, index=True)
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))


class Trade(SQLModel, table=True):
    """Executed trade event."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    venue: Venue = Field(index=True)
    venue_order_id: str | None = Field(default=None, index=True)
    market_id: str = Field(foreign_key="market.id", index=True)
    outcome: str = Field(index=True)
    side: TradeSide
    price: Decimal = Field(max_digits=12, decimal_places=6)
    size: Decimal = Field(max_digits=18, decimal_places=6)
    fees: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=6)
    strategy_name: str | None = Field(default=None, index=True)
    executed_at: datetime = Field(default_factory=utc_now, index=True)
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
