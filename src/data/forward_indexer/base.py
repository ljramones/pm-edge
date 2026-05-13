"""Abstract venue indexer contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .book_state import BookState


@dataclass(frozen=True)
class MarketDescriptor:
    """Normalized market metadata used by the forward indexer."""

    venue: str
    market_id: str
    question: str
    token_id_yes: str = ""
    token_id_no: str = ""
    status: str = "unknown"
    volume_24h: float | None = None
    liquidity: float | None = None
    spread: float | None = None
    end_date: datetime | None = None
    last_trade_at: datetime | None = None
    created_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class VenueStats:
    """Operational counters for one venue indexer."""

    venue: str
    markets_discovered: int = 0
    markets_tracked: int = 0
    websocket_connections: int = 0
    errors_since_heartbeat: int = 0


class VenueIndexer(ABC):
    """Abstract interface implemented by venue-specific forward indexers."""

    venue: str

    @abstractmethod
    async def discover_markets(self) -> list[MarketDescriptor]:
        """Discover public markets and return normalized metadata."""

    @abstractmethod
    async def subscribe_books(self, markets: list[MarketDescriptor]) -> None:
        """Maintain live book state for the supplied active markets."""

    @abstractmethod
    async def subscribe_trades(self, markets: list[MarketDescriptor]) -> None:
        """Capture live trade events for the supplied active markets."""

    @abstractmethod
    async def current_book_state(self, market_id: str) -> BookState | None:
        """Return current in-memory book state for one market."""

    @abstractmethod
    async def flush_pending(self) -> None:
        """Flush any venue-owned buffers before shutdown."""

    @abstractmethod
    def stats(self) -> VenueStats:
        """Return heartbeat counters."""
