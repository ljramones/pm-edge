"""Async-safe in-memory order-book state for forward indexing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .schemas import SCHEMA_VERSION

BookSide = Literal["bid", "ask"]


@dataclass(frozen=True)
class PriceLevel:
    """One order-book price level."""

    price: float
    size: float

    def as_dict(self) -> dict[str, float]:
        """Return a parquet-friendly representation."""

        return {"price": self.price, "size": self.size}


class BookState:
    """Maintain top-N bid/ask state under an asyncio lock."""

    def __init__(
        self,
        *,
        venue: str,
        market_id: str,
        token_id_yes: str | None = None,
        token_id_no: str | None = None,
        depth: int = 5,
    ) -> None:
        self.venue = venue
        self.market_id = market_id
        self.token_id_yes = token_id_yes or ""
        self.token_id_no = token_id_no or ""
        self.depth = depth
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}
        self._snapshot_source = "rest"
        self._updated_at = datetime.now(tz=UTC)
        self._lock = asyncio.Lock()

    async def replace(
        self,
        *,
        bids: list[dict[str, float]] | list[PriceLevel],
        asks: list[dict[str, float]] | list[PriceLevel],
        source: str = "rest",
        timestamp: datetime | None = None,
    ) -> None:
        """Replace the full visible book state."""

        async with self._lock:
            self._bids = _levels_to_dict(bids)
            self._asks = _levels_to_dict(asks)
            self._trim_unlocked()
            self._snapshot_source = source
            self._updated_at = timestamp or datetime.now(tz=UTC)

    async def apply_diff(
        self,
        *,
        side: BookSide,
        price: float,
        size: float,
        source: str = "websocket",
        timestamp: datetime | None = None,
    ) -> None:
        """Apply one price-level update."""

        async with self._lock:
            book_side = self._bids if side == "bid" else self._asks
            if size <= 0:
                book_side.pop(float(price), None)
            else:
                book_side[float(price)] = float(size)
            self._trim_unlocked()
            self._snapshot_source = source
            self._updated_at = timestamp or datetime.now(tz=UTC)

    async def snapshot(self, *, timestamp: datetime | None = None) -> dict[str, object]:
        """Return a parquet-ready top-N snapshot."""

        async with self._lock:
            bids = _sorted_bids(self._bids, self.depth)
            asks = _sorted_asks(self._asks, self.depth)
            top_bid = bids[0].price if bids else None
            top_ask = asks[0].price if asks else None
            spread = top_ask - top_bid if top_bid is not None and top_ask is not None else None
            mid = (top_bid + top_ask) / 2 if top_bid is not None and top_ask is not None else None
            return {
                "schema_version": SCHEMA_VERSION,
                "venue": self.venue,
                "market_id": self.market_id,
                "token_id_yes": self.token_id_yes,
                "token_id_no": self.token_id_no,
                "timestamp_utc": timestamp or datetime.now(tz=UTC),
                "bid_levels": [level.as_dict() for level in bids],
                "ask_levels": [level.as_dict() for level in asks],
                "top_bid": top_bid,
                "top_ask": top_ask,
                "mid": mid,
                "spread": spread,
                "snapshot_source": self._snapshot_source,
            }

    def _trim_unlocked(self) -> None:
        self._bids = {level.price: level.size for level in _sorted_bids(self._bids, self.depth)}
        self._asks = {level.price: level.size for level in _sorted_asks(self._asks, self.depth)}


def _levels_to_dict(levels: list[dict[str, float]] | list[PriceLevel]) -> dict[float, float]:
    output: dict[float, float] = {}
    for level in levels:
        price = level.price if isinstance(level, PriceLevel) else float(level["price"])
        size = level.size if isinstance(level, PriceLevel) else float(level["size"])
        if size > 0:
            output[float(price)] = float(size)
    return output


def _sorted_bids(levels: dict[float, float], depth: int) -> list[PriceLevel]:
    return [
        PriceLevel(price=price, size=size)
        for price, size in sorted(levels.items(), key=lambda item: item[0], reverse=True)[:depth]
    ]


def _sorted_asks(levels: dict[float, float], depth: int) -> list[PriceLevel]:
    return [
        PriceLevel(price=price, size=size)
        for price, size in sorted(levels.items(), key=lambda item: item[0])[:depth]
    ]
