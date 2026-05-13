"""Database models for unified prediction market state."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, Column
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


class PollObservation(SQLModel, table=True):
    """Normalized poll observation for an event or market."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    event_slug: str = Field(index=True)
    market_id: str | None = Field(default=None, index=True)
    pollster: str = Field(index=True)
    pollster_grade: str | None = None
    population: str | None = None
    sample_size: int | None = None
    start_date: datetime | None = None
    end_date: datetime = Field(index=True)
    candidate: str
    support: Decimal = Field(max_digits=12, decimal_places=6)
    weight: Decimal = Field(max_digits=12, decimal_places=6)
    source_url: str | None = None
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class PollAggregateRecord(SQLModel, table=True):
    """Daily weighted poll aggregate for an event or market."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    event_slug: str = Field(index=True)
    market_id: str | None = Field(default=None, index=True)
    as_of: datetime = Field(index=True)
    candidate: str = Field(index=True)
    probability: Decimal = Field(max_digits=12, decimal_places=6)
    poll_count: int
    effective_sample_size: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=6)
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class SentimentVectorRecord(SQLModel, table=True):
    """Daily news and sentiment feature vector linked to a market/event."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    event_slug: str = Field(index=True)
    market_id: str | None = Field(default=None, index=True)
    as_of: datetime = Field(index=True)
    mention_count_24h: int = 0
    mention_count_7d: int = 0
    sentiment_24h: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=6)
    sentiment_7d: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=6)
    tone_shift: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=6)
    linked_entities: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class FeatureVectorRecord(SQLModel, table=True):
    """Materialized feature vector used for model training or scoring."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    market_id: str = Field(index=True)
    event_slug: str | None = Field(default=None, index=True)
    as_of: datetime = Field(default_factory=utc_now, index=True)
    features: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    market_probability: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    resolved_probability: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class BacktestRun(SQLModel, table=True):
    """Backtest run metadata and aggregate output."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    strategy_name: str = Field(index=True)
    started_at: datetime = Field(default_factory=utc_now, index=True)
    period_start: datetime | None = Field(default=None, index=True)
    period_end: datetime | None = Field(default=None, index=True)
    config: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    metrics: dict[str, float | str] = Field(default_factory=dict, sa_column=Column(JSON))
    rubric_grade: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class BacktestBet(SQLModel, table=True):
    """Simulated backtest bet and realized outcome."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="backtestrun.id", index=True)
    market_id: str = Field(index=True)
    category: str | None = Field(default=None, index=True)
    signal_time: datetime = Field(index=True)
    resolution_time: datetime | None = Field(default=None, index=True)
    market_probability: Decimal = Field(max_digits=12, decimal_places=6)
    model_probability: Decimal = Field(max_digits=12, decimal_places=6)
    edge: Decimal = Field(max_digits=12, decimal_places=6)
    threshold: Decimal = Field(max_digits=12, decimal_places=6)
    stake: Decimal = Field(max_digits=18, decimal_places=6)
    entry_price: Decimal = Field(max_digits=12, decimal_places=6)
    slippage: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=6)
    fee: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=6)
    outcome: int = Field(index=True)
    pnl: Decimal = Field(max_digits=18, decimal_places=6)
    return_on_capital: Decimal = Field(max_digits=12, decimal_places=6)
    raw: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))


class OrderBookSnapshot(SQLModel, table=True):
    """Forward-indexed order book snapshot for simulator-grade replay."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    venue: Venue = Field(index=True)
    market_id: str = Field(index=True)
    token_id_yes: str | None = Field(default=None, index=True)
    token_id_no: str | None = Field(default=None, index=True)
    timestamp_utc: datetime = Field(default_factory=utc_now, index=True)
    bid_levels: list[dict[str, float]] = Field(default_factory=list, sa_column=Column(JSON))
    ask_levels: list[dict[str, float]] = Field(default_factory=list, sa_column=Column(JSON))
    top_bid: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    top_ask: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    mid: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    spread: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)
    snapshot_source: str = Field(index=True)
    schema_version: int = Field(default=1, index=True)


class TradeEvent(SQLModel, table=True):
    """Forward-indexed public trade event."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    venue: Venue = Field(index=True)
    market_id: str = Field(index=True)
    token_id: str | None = Field(default=None, index=True)
    timestamp_utc: datetime = Field(default_factory=utc_now, index=True)
    price: Decimal = Field(max_digits=12, decimal_places=6)
    size: Decimal = Field(max_digits=18, decimal_places=6)
    side: str | None = Field(default=None, index=True)
    trade_id_venue: str | None = Field(default=None, index=True)
    schema_version: int = Field(default=1, index=True)


class MarketMetadataSnapshot(SQLModel, table=True):
    """Forward-indexed market metadata snapshot."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    venue: Venue = Field(index=True)
    market_id: str = Field(index=True)
    captured_at_utc: datetime = Field(default_factory=utc_now, index=True)
    status: str = Field(index=True)
    volume_24h: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    liquidity: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    end_date: datetime | None = Field(default=None, index=True)
    raw_json: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    schema_version: int = Field(default=1, index=True)
