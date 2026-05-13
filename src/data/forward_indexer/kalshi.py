"""Kalshi forward indexer using public REST and WebSocket market data."""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from utils.logging import get_logger

from .base import MarketDescriptor, VenueIndexer, VenueStats
from .book_state import BookState
from .schemas import SCHEMA_VERSION

WsConnect = Callable[[str], Awaitable[Any]]


class KalshiIndexer(VenueIndexer):
    """Maintain public Kalshi market metadata, reconstructed books, and trades."""

    venue = "kalshi"

    def __init__(
        self,
        *,
        base_url: str,
        depth: int = 5,
        client: Any | None = None,
        ws_connect: WsConnect | None = None,
        request_delay_seconds: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("https://", "wss://").replace(
            "/trade-api/v2", "/trade-api/ws/v2"
        )
        self.depth = depth
        self.request_delay = request_delay_seconds
        self.client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        self.ws_connect = ws_connect
        self.books: dict[str, BookState] = {}
        self.trade_buffer: list[dict[str, Any]] = []
        self._stats = VenueStats(venue=self.venue)
        self._logger = get_logger(__name__)
        self._stop = asyncio.Event()

    async def close(self) -> None:
        """Close owned resources."""

        self._stop.set()
        if self._owns_client:
            await self.client.aclose()

    async def discover_markets(self) -> list[MarketDescriptor]:
        """Discover Kalshi markets through the public markets endpoint."""

        markets: list[MarketDescriptor] = []
        cursor: str | None = None
        while True:
            params = {"limit": "1000", "status": "open"}
            if cursor:
                params["cursor"] = cursor
            payload = await self._request_json(f"{self.base_url}/markets", params=params)
            for item in payload.get("markets", []):
                if isinstance(item, dict):
                    market = self._market_from_payload(item)
                    if market is not None:
                        markets.append(market)
            cursor_value = payload.get("cursor")
            if not cursor_value:
                break
            cursor = str(cursor_value)
        self._stats.markets_discovered = len(markets)
        return markets

    async def subscribe_books(self, markets: list[MarketDescriptor]) -> None:
        """Subscribe to Kalshi orderbook deltas with REST refresh on reconnect."""

        for market in markets:
            await self.refresh_book(market)
        self._stats.markets_tracked = len(markets)
        if self.ws_connect is None or not markets:
            return
        self._stats.websocket_connections = 1
        await self._book_ws_loop(markets)

    async def subscribe_trades(self, markets: list[MarketDescriptor]) -> None:
        """Kalshi trade events are captured from WebSocket messages when available."""

        self._stats.markets_tracked = max(self._stats.markets_tracked, len(markets))

    async def current_book_state(self, market_id: str) -> BookState | None:
        """Return current book state for one market."""

        return self.books.get(market_id)

    async def flush_pending(self) -> None:
        """No-op; trade events are drained by the runner."""

    def stats(self) -> VenueStats:
        """Return current operational counters."""

        return self._stats

    async def drain_trade_events(self) -> list[dict[str, Any]]:
        """Return and clear buffered trade events."""

        events = list(self.trade_buffer)
        self.trade_buffer.clear()
        return events

    async def refresh_book(self, market: MarketDescriptor) -> None:
        """Fetch the REST orderbook and reconstruct YES asks from NO bids."""

        payload = await self._request_json(f"{self.base_url}/markets/{market.market_id}/orderbook")
        orderbook = (
            payload.get("orderbook") if isinstance(payload.get("orderbook"), dict) else payload
        )
        if not isinstance(orderbook, dict):
            orderbook = {}
        yes_bids = _levels_from_kalshi(orderbook.get("yes") or orderbook.get("yes_bids") or [])
        no_bids = _levels_from_kalshi(orderbook.get("no") or orderbook.get("no_bids") or [])
        asks = [{"price": 1 - level["price"], "size": level["size"]} for level in no_bids]
        state = self.books.get(market.market_id)
        if state is None:
            state = BookState(
                venue=self.venue,
                market_id=market.market_id,
                token_id_yes=market.token_id_yes,
                token_id_no=market.token_id_no,
                depth=self.depth,
            )
            self.books[market.market_id] = state
        await state.replace(
            bids=yes_bids,
            asks=asks,
            source="reconstructed_from_complement",
        )

    async def _book_ws_loop(self, markets: list[MarketDescriptor]) -> None:
        backoff = 1.0
        market_ids = [market.market_id for market in markets]
        while not self._stop.is_set():
            try:
                if self.ws_connect is None:
                    return
                ws = await self.ws_connect(self.ws_url)
                await ws.send(
                    json.dumps(
                        {
                            "id": 1,
                            "cmd": "subscribe",
                            "params": {
                                "channels": ["orderbook_delta", "trade"],
                                "market_tickers": market_ids,
                            },
                        }
                    )
                )
                backoff = 1.0
                async for raw in ws:
                    await self._handle_ws_message(raw, markets)
            except Exception as exc:
                self._stats.errors_since_heartbeat += 1
                self._logger.warning("kalshi_ws_reconnect", error=str(exc), backoff=backoff)
                await asyncio.gather(*(self.refresh_book(market) for market in markets))
                await asyncio.sleep(backoff + random.uniform(0, backoff * 0.1))
                backoff = min(backoff * 2, 60.0)

    async def _handle_ws_message(self, raw: str | bytes, markets: list[MarketDescriptor]) -> None:
        payload = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        message = payload.get("msg", payload) if isinstance(payload, dict) else {}
        if not isinstance(message, dict):
            return
        market_id = str(
            message.get("market_ticker") or message.get("market_id") or message.get("ticker") or ""
        )
        market = next((item for item in markets if item.market_id == market_id), None)
        if market is None:
            return
        msg_type = str(payload.get("type") or message.get("type") or "").lower()
        if "trade" in msg_type:
            self._append_trade(market, message)
        elif "orderbook" in msg_type or "delta" in msg_type:
            await self._apply_book_delta(market, message)

    async def _apply_book_delta(self, market: MarketDescriptor, message: dict[str, Any]) -> None:
        state = self.books.get(market.market_id)
        if state is None:
            await self.refresh_book(market)
            state = self.books.get(market.market_id)
        if state is None:
            return
        side = str(message.get("side") or "").lower()
        price = _float_or_none(message.get("price"))
        delta = _float_or_none(message.get("delta") or message.get("size"))
        if price is None or delta is None:
            return
        if side == "no":
            await state.apply_diff(
                side="ask", price=1 - price, size=max(delta, 0), source="websocket"
            )
        else:
            await state.apply_diff(side="bid", price=price, size=max(delta, 0), source="websocket")

    def _append_trade(self, market: MarketDescriptor, message: dict[str, Any]) -> None:
        price = _float_or_none(message.get("price"))
        size = _float_or_none(message.get("count") or message.get("size"))
        if price is None or size is None:
            return
        self.trade_buffer.append(
            {
                "schema_version": SCHEMA_VERSION,
                "venue": self.venue,
                "market_id": market.market_id,
                "token_id": str(message.get("yes_no") or ""),
                "timestamp_utc": datetime.now(tz=UTC),
                "price": price,
                "size": size,
                "side": str(message.get("taker_side") or message.get("side") or "").lower(),
                "trade_id_venue": str(message.get("trade_id") or message.get("id") or ""),
            }
        )

    async def _request_json(
        self, url: str, *, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        backoff = 1.0
        while True:
            response = await self.client.get(url, params=params)
            if response.status_code != 429:
                response.raise_for_status()
                payload = dict(response.json())
                if self.request_delay > 0:
                    await asyncio.sleep(self.request_delay)
                return payload
            await asyncio.sleep(backoff + random.uniform(0, backoff * 0.1))
            backoff = min(backoff * 2, 60.0)

    def _market_from_payload(self, item: dict[str, Any]) -> MarketDescriptor | None:
        ticker = str(item.get("ticker") or item.get("market_ticker") or "")
        if not ticker:
            return None
        yes_bid = _normalized_price(item.get("yes_bid") or item.get("yes_bid_dollars"))
        yes_ask = _normalized_price(item.get("yes_ask") or item.get("yes_ask_dollars"))
        spread = yes_ask - yes_bid if yes_bid is not None and yes_ask is not None else None
        return MarketDescriptor(
            venue=self.venue,
            market_id=ticker,
            question=str(item.get("title") or item.get("event_title") or ticker),
            token_id_yes=f"{ticker}:yes",
            token_id_no=f"{ticker}:no",
            status=str(item.get("status") or "unknown"),
            volume_24h=_float_or_none(
                item.get("volume_24h") or item.get("volume_24h_fp") or item.get("volume")
            ),
            liquidity=_float_or_none(
                item.get("liquidity") or item.get("open_interest") or item.get("open_interest_fp")
            ),
            spread=spread,
            end_date=_parse_datetime(item.get("close_time") or item.get("expiration_time")),
            last_trade_at=_parse_datetime(
                item.get("last_trade_time")
                or item.get("last_trade_at")
                or item.get("last_price_time")
                or item.get("last_price_at")
                or item.get("updated_time")
            ),
            created_at=_parse_datetime(item.get("open_time") or item.get("created_time")),
            raw=_compact_raw(item),
        )


def _levels_from_kalshi(levels: list[Any]) -> list[dict[str, float]]:
    output = []
    for level in levels:
        if isinstance(level, dict):
            price = _float_or_none(level.get("price"))
            size = _float_or_none(level.get("size") or level.get("count"))
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price = _float_or_none(level[0])
            size = _float_or_none(level[1])
        else:
            continue
        if price is None or size is None:
            continue
        if price > 1:
            price = price / 100
        output.append({"price": price, "size": size})
    return output


def _normalized_price(value: Any) -> float | None:
    price = _float_or_none(value)
    if price is None:
        return None
    return price / 100 if price > 1 else price


def _compact_raw(item: dict[str, Any]) -> dict[str, Any]:
    """Keep scalar metadata fields without retaining large nested venue payloads."""

    return {
        key: value
        for key, value in item.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None
