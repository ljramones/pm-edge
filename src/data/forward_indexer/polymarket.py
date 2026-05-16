"""Polymarket forward indexer using public CLOB REST and market WebSocket data."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from core.config import get_settings
from utils.logging import get_logger

from .base import MarketDescriptor, VenueIndexer, VenueStats
from .book_state import BookSide, BookState
from .schemas import SCHEMA_VERSION

POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

WsConnect = Callable[[str], Awaitable[Any]]


class PolymarketIndexer(VenueIndexer):
    """Maintain public Polymarket market metadata, book state, and trades."""

    venue = "polymarket"

    def __init__(
        self,
        *,
        base_url: str,
        depth: int = 5,
        client: Any | None = None,
        ws_connect: WsConnect | None = None,
        max_ws_connections: int = 4,
        gamma_url: str | None = None,
        min_volume_usd: float = 10_000.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.gamma_url = (gamma_url or get_settings().polymarket_gamma_url).rstrip("/")
        self.depth = depth
        self.min_volume_usd = min_volume_usd
        self.client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        self.ws_connect = ws_connect
        self.max_ws_connections = max_ws_connections
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
        """Discover active markets through Gamma metadata keyset pagination."""

        markets: list[MarketDescriptor] = []
        cursor: str | None = None
        skipped_pages = 0
        while True:
            params = {
                "closed": "false",
                "active": "true",
                "archived": "false",
                "enableOrderBook": "true",
                "acceptingOrders": "true",
                "include_tag": "true",
                "limit": "500",
                "order": "volume_num",
                "ascending": "false",
                "volume_num_min": str(self.min_volume_usd),
            }
            if cursor:
                params["after_cursor"] = cursor
            url = f"{self.gamma_url}/markets/keyset"
            payload = await self._request_gamma_page(
                url,
                params=params,
                cursor=cursor,
            )
            if payload is None:
                skipped_pages += 1
                self._logger.error(
                    "polymarket_discovery_aborted",
                    cursor=cursor,
                    url=url,
                    markets_collected=len(markets),
                    skipped_pages=skipped_pages,
                )
                break
            page = payload.get("data") or payload.get("markets") or []
            for item in page:
                if not isinstance(item, dict):
                    continue
                market = self._market_from_payload(item)
                if market is not None:
                    markets.append(market)
            next_cursor = payload.get("next_cursor") or payload.get("cursor")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = str(next_cursor)
        self._stats.markets_discovered = len(markets)
        return markets

    async def _request_gamma_page(
        self,
        url: str,
        *,
        params: dict[str, str],
        cursor: str | None,
    ) -> dict[str, Any] | None:
        """Fetch one Gamma discovery page with bounded transient retries."""

        backoff = 1.0
        max_retries = 6
        max_attempts = max_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                response = await self.client.get(url, params=params)
            except httpx.RequestError as exc:
                self._stats.errors_since_heartbeat += 1
                self._logger.warning(
                    "polymarket_gamma_page_retry",
                    attempt=attempt,
                    cursor=cursor,
                    error=str(exc),
                    backoff=backoff,
                    url=url,
                )
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    self._stats.errors_since_heartbeat += 1
                    self._logger.warning(
                        "polymarket_gamma_page_retry",
                        attempt=attempt,
                        cursor=cursor,
                        status_code=response.status_code,
                        backoff=backoff,
                        url=url,
                    )
                elif response.status_code >= 400:
                    self._stats.errors_since_heartbeat += 1
                    self._logger.error(
                        "polymarket_gamma_page_failed",
                        cursor=cursor,
                        status_code=response.status_code,
                        url=url,
                    )
                    return None
                else:
                    return dict(response.json())
            if attempt < max_attempts:
                await asyncio.sleep(backoff + random.uniform(0, backoff * 0.1))
                backoff = min(backoff * 2, 30.0)
        self._logger.error(
            "polymarket_gamma_page_failed",
            cursor=cursor,
            attempts=max_attempts,
            url=url,
        )
        return None

    async def subscribe_books(self, markets: list[MarketDescriptor]) -> None:
        """Subscribe to book diffs, with REST refresh on initial state and reconnect."""

        for market in markets:
            await self.refresh_book(market)
        self._stats.markets_tracked = len(markets)
        if self.ws_connect is None:
            return
        chunks = _chunk_markets(markets, self.max_ws_connections)
        self._stats.websocket_connections = len(chunks)
        await asyncio.gather(*(self._book_ws_loop(chunk) for chunk in chunks))

    async def subscribe_trades(self, markets: list[MarketDescriptor]) -> None:
        """Polymarket market WebSocket messages include trade events when emitted."""

        self._stats.markets_tracked = max(self._stats.markets_tracked, len(markets))

    async def current_book_state(self, market_id: str) -> BookState | None:
        """Return the current book state for one market."""

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
        """Fetch current REST book state for one market."""

        if not market.token_id_yes:
            return
        try:
            payload = await self._request_json(
                f"{self.base_url}/book", params={"token_id": market.token_id_yes}
            )
        except httpx.HTTPStatusError as exc:
            self._stats.errors_since_heartbeat += 1
            self._logger.warning(
                "polymarket_book_refresh_skipped",
                market_id=market.market_id,
                token_id=market.token_id_yes,
                status_code=exc.response.status_code,
            )
            return
        bids = _levels_from_payload(payload.get("bids") or payload.get("buys") or [])
        asks = _levels_from_payload(payload.get("asks") or payload.get("sells") or [])
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
        await state.replace(bids=bids, asks=asks, source="rest")

    async def fetch_market_metadata(self, market: MarketDescriptor) -> MarketDescriptor | None:
        """Fetch one market metadata payload directly by condition id."""

        try:
            payload = await self._request_json(f"{self.base_url}/markets/{market.market_id}")
        except httpx.HTTPStatusError as exc:
            self._stats.errors_since_heartbeat += 1
            self._logger.warning(
                "polymarket_metadata_refresh_skipped",
                market_id=market.market_id,
                status_code=exc.response.status_code,
            )
            return None
        return self._market_from_payload(payload)

    async def _book_ws_loop(self, markets: list[MarketDescriptor]) -> None:
        backoff = 1.0
        asset_ids = [market.token_id_yes for market in markets if market.token_id_yes]
        while not self._stop.is_set():
            try:
                if self.ws_connect is None:
                    return
                ws = await self.ws_connect(POLYMARKET_WS_URL)
                await ws.send(json.dumps({"type": "market", "assets_ids": asset_ids}))
                backoff = 1.0
                async for raw in ws:
                    await self._handle_ws_message(raw, markets)
            except Exception as exc:
                self._stats.errors_since_heartbeat += 1
                self._logger.warning("polymarket_ws_reconnect", error=str(exc), backoff=backoff)
                await asyncio.gather(*(self.refresh_book(market) for market in markets))
                await asyncio.sleep(backoff + random.uniform(0, backoff * 0.1))
                backoff = min(backoff * 2, 60.0)

    async def _handle_ws_message(self, raw: str | bytes, markets: list[MarketDescriptor]) -> None:
        payload = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        messages = payload if isinstance(payload, list) else [payload]
        token_to_market = {market.token_id_yes: market for market in markets if market.token_id_yes}
        for message in messages:
            if not isinstance(message, dict):
                continue
            event_type = str(message.get("event_type") or message.get("type") or "").lower()
            token_id = str(message.get("asset_id") or message.get("token_id") or "")
            market = token_to_market.get(token_id)
            if event_type in {"price_change", "book", "orderbook"}:
                await self._apply_book_message(message, token_to_market, market)
            elif event_type in {"trade", "last_trade_price", "trade_executed"}:
                if market is None:
                    continue
                self._append_trade(market, message, token_id)

    async def _apply_book_message(
        self,
        message: dict[str, Any],
        token_to_market: dict[str, MarketDescriptor],
        market: MarketDescriptor | None,
    ) -> None:
        if market is not None and (
            message.get("bids") is not None or message.get("asks") is not None
        ):
            await self._replace_book_from_ws(market, message)
            return
        changes = message.get("changes") or message.get("price_changes") or []
        for change in changes:
            if not isinstance(change, dict):
                continue
            change_token_id = str(
                change.get("asset_id")
                or change.get("token_id")
                or message.get("asset_id")
                or message.get("token_id")
                or ""
            )
            change_market = token_to_market.get(change_token_id)
            if change_market is not None:
                await self._apply_book_change(change_market, change)

    async def _replace_book_from_ws(
        self, market: MarketDescriptor, message: dict[str, Any]
    ) -> None:
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
        bids = _levels_from_payload(message.get("bids") or message.get("buys") or [])
        asks = _levels_from_payload(message.get("asks") or message.get("sells") or [])
        await state.replace(bids=bids, asks=asks, source="websocket")

    async def _apply_book_change(self, market: MarketDescriptor, change: dict[str, Any]) -> None:
        state = self.books.get(market.market_id)
        if state is None:
            await self.refresh_book(market)
            state = self.books.get(market.market_id)
        if state is None:
            return
        side = str(change.get("side") or change.get("book_side") or "").lower()
        price = _float_or_none(change.get("price"))
        size = _float_or_none(change.get("size"))
        if price is None or size is None:
            return
        book_side: BookSide = "bid" if side in {"buy", "bid", "bids"} else "ask"
        await state.apply_diff(side=book_side, price=price, size=size, source="websocket")

    def _append_trade(
        self, market: MarketDescriptor, message: dict[str, Any], token_id: str
    ) -> None:
        price = _float_or_none(message.get("price") or message.get("last_price"))
        size = _float_or_none(message.get("size") or message.get("amount"))
        if price is None or size is None:
            return
        timestamp_utc = _trade_timestamp(message) or datetime.now(tz=UTC)
        side = str(message.get("side") or "").lower()
        self.trade_buffer.append(
            {
                "schema_version": SCHEMA_VERSION,
                "venue": self.venue,
                "market_id": market.market_id,
                "token_id": token_id,
                "timestamp_utc": timestamp_utc,
                "price": price,
                "size": size,
                "side": side,
                "trade_id_venue": _trade_id_venue(
                    message=message,
                    market_id=market.market_id,
                    token_id=token_id,
                    timestamp_utc=timestamp_utc,
                    price=price,
                    size=size,
                    side=side,
                ),
            }
        )

    async def _request_json(
        self, url: str, *, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        backoff = 1.0
        while True:
            try:
                response = await self.client.get(url, params=params)
                if response.status_code != 429:
                    response.raise_for_status()
                    return dict(response.json())
            except httpx.RequestError as exc:
                self._stats.errors_since_heartbeat += 1
                self._logger.warning(
                    "polymarket_request_retry",
                    error=str(exc),
                    backoff=backoff,
                    url=url,
                )
            await asyncio.sleep(backoff + random.uniform(0, backoff * 0.1))
            backoff = min(backoff * 2, 60.0)

    def _market_from_payload(self, item: dict[str, Any]) -> MarketDescriptor | None:
        market_id = str(item.get("condition_id") or item.get("conditionId") or item.get("id") or "")
        if not market_id:
            return None
        closed = _bool_or_none(item.get("closed"))
        active = _bool_or_none(item.get("active"))
        archived = _bool_or_none(item.get("archived"))
        accepting_orders = _bool_or_none(item.get("acceptingOrders"))
        resolution_outcome = _polymarket_resolution_outcome(item)
        resolution_timestamp = _parse_datetime(
            item.get("resolutionTime")
            or item.get("resolution_time")
            or item.get("resolvedAt")
            or item.get("resolved_at")
            or item.get("closedTime")
            or item.get("closed_time")
        )
        raw_tokens = item.get("tokens")
        tokens: list[Any] = raw_tokens if isinstance(raw_tokens, list) else []
        clob_token_ids = _list_from_jsonish(item.get("clobTokenIds") or item.get("clob_token_ids"))
        token_id_yes = (
            _token_id_for(tokens, "yes")
            or str(item.get("token_id_yes") or "")
            or (str(clob_token_ids[0]) if clob_token_ids else "")
        )
        token_id_no = (
            _token_id_for(tokens, "no")
            or str(item.get("token_id_no") or "")
            or (str(clob_token_ids[1]) if len(clob_token_ids) > 1 else "")
        )
        return MarketDescriptor(
            venue=self.venue,
            market_id=market_id,
            question=str(item.get("question") or item.get("description") or market_id),
            token_id_yes=token_id_yes,
            token_id_no=token_id_no,
            status=str(item.get("active") or item.get("status") or "active"),
            venue_status_raw=_polymarket_status_raw(
                closed=closed,
                active=active,
                archived=archived,
            ),
            is_closed=closed,
            is_archived=archived,
            is_resolved=_polymarket_is_resolved(
                item,
                closed=closed,
                resolution_outcome=resolution_outcome,
                resolution_timestamp=resolution_timestamp,
            ),
            resolution_outcome=resolution_outcome,
            resolution_timestamp_utc=resolution_timestamp,
            accepting_orders=accepting_orders,
            volume_24h=_float_or_none(
                item.get("volume_24hr")
                or item.get("volume24hr")
                or item.get("volume24hrClob")
                or item.get("volumeNum")
                or item.get("volume")
            ),
            liquidity=_float_or_none(
                item.get("liquidity") or item.get("liquidity_num") or item.get("liquidityNum")
            ),
            spread=_float_or_none(item.get("spread")),
            end_date=_parse_datetime(
                item.get("end_date_iso")
                or item.get("end_date")
                or item.get("endDateIso")
                or item.get("endDate")
            ),
            last_trade_at=_parse_datetime(
                item.get("lastTradeAt")
                or item.get("last_trade_at")
                or item.get("lastTradeTime")
                or item.get("last_trade_time")
                or item.get("lastActivity")
                or item.get("last_activity")
                or item.get("lastActiveAt")
                or item.get("updatedAt")
                or item.get("updated_at")
            ),
            created_at=_parse_datetime(
                item.get("createdAt")
                or item.get("created_at")
                or item.get("startDate")
                or item.get("startDateIso")
            ),
            raw=_compact_raw(item),
        )


def _token_id_for(tokens: list[Any], outcome: str) -> str:
    for token in tokens:
        if not isinstance(token, dict):
            continue
        token_outcome = str(token.get("outcome") or "").lower()
        if token_outcome == outcome:
            return str(token.get("token_id") or token.get("id") or "")
    return ""


def _list_from_jsonish(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _compact_raw(item: dict[str, Any]) -> dict[str, Any]:
    """Keep scalar metadata fields without retaining large nested Gamma payloads."""

    return {
        key: value
        for key, value in item.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }


def _polymarket_status_raw(
    *,
    closed: bool | None,
    active: bool | None,
    archived: bool | None,
) -> str:
    if closed is True and archived is True:
        return "archived"
    if closed is True:
        return "closed"
    if closed is False and active is True:
        return "active"
    if closed is False and active is False:
        return "inactive"
    if archived is True:
        return "archived"
    if active is True:
        return "active"
    if active is False:
        return "inactive"
    return "unknown"


def _polymarket_is_resolved(
    item: dict[str, Any],
    *,
    closed: bool | None,
    resolution_outcome: str | None,
    resolution_timestamp: datetime | None,
) -> bool:
    if resolution_outcome is not None or resolution_timestamp is not None:
        return True
    statuses = _list_from_jsonish(
        item.get("umaResolutionStatuses") or item.get("uma_resolution_statuses")
    )
    status_text = " ".join(str(status).lower() for status in statuses)
    status_text += " "
    status_text += str(
        item.get("umaResolutionStatus") or item.get("uma_resolution_status") or ""
    ).lower()
    return closed is True and any(
        marker in status_text for marker in ("resolved", "settled", "final")
    )


def _polymarket_resolution_outcome(item: dict[str, Any]) -> str | None:
    for field in (
        "resolvedOutcome",
        "resolved_outcome",
        "winningOutcome",
        "winning_outcome",
        "winner",
        "outcome",
    ):
        outcome = _normalized_yes_no(item.get(field))
        if outcome is not None:
            return outcome
    index_value = item.get("winningOutcomeIndex") or item.get("winning_outcome_index")
    if index_value is not None:
        try:
            return "YES" if int(index_value) == 0 else "NO"
        except (TypeError, ValueError):
            return None
    resolved_by = item.get("resolvedBy") or item.get("resolved_by")
    return _normalized_yes_no(resolved_by)


def _normalized_yes_no(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"yes", "y", "true", "1"}:
        return "YES"
    if text in {"no", "n", "false", "0"}:
        return "NO"
    return None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _levels_from_payload(levels: list[Any]) -> list[dict[str, float]]:
    output = []
    for level in levels:
        if isinstance(level, dict):
            price = _float_or_none(level.get("price"))
            size = _float_or_none(level.get("size"))
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price = _float_or_none(level[0])
            size = _float_or_none(level[1])
        else:
            continue
        if price is not None and size is not None:
            output.append({"price": price, "size": size})
    return output


def _chunk_markets(
    markets: list[MarketDescriptor], max_chunks: int
) -> list[list[MarketDescriptor]]:
    if not markets:
        return []
    chunk_count = min(max_chunks, len(markets))
    return [markets[index::chunk_count] for index in range(chunk_count)]


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_id_venue(
    *,
    message: dict[str, Any],
    market_id: str,
    token_id: str,
    timestamp_utc: datetime,
    price: float,
    size: float,
    side: str,
) -> str:
    for field in (
        "trade_id",
        "tradeId",
        "id",
        "hash",
        "tx_hash",
        "transaction_hash",
        "transactionHash",
        "taker_order_id",
        "takerOrderId",
        "maker_order_id",
        "makerOrderId",
    ):
        value = message.get(field)
        if value:
            return str(value)
    digest = hashlib.sha256(
        "|".join(
            [
                market_id,
                token_id,
                timestamp_utc.isoformat(),
                f"{price:.12g}",
                f"{size:.12g}",
                side,
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"synthetic:{digest}"


def _trade_timestamp(message: dict[str, Any]) -> datetime | None:
    value = (
        message.get("timestamp")
        or message.get("time")
        or message.get("created_at")
        or message.get("createdAt")
    )
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _timestamp_from_epoch(float(value))
    text = str(value)
    parsed = _parse_datetime(text)
    if parsed is not None:
        return parsed
    try:
        return _timestamp_from_epoch(float(text))
    except ValueError:
        return None


def _timestamp_from_epoch(value: float) -> datetime:
    if value > 10_000_000_000:
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=UTC)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None
