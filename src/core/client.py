"""Async unified prediction market client.

The client is intentionally thin: it normalizes the interface used by the rest
of the system while delegating venue-specific details to PMXT first, then to
direct Polymarket and Kalshi SDK adapters when PMXT is unavailable.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import Settings, get_settings
from utils.logging import get_logger

logger = get_logger(__name__)


class Venue(StrEnum):
    """Supported prediction market venues."""

    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class OrderSide(StrEnum):
    """Order side for binary prediction market contracts."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Supported order types."""

    LIMIT = "limit"
    MARKET = "market"


class UnifiedMarket(BaseModel):
    """Venue-agnostic market representation returned by client fetches."""

    model_config = ConfigDict(frozen=True)

    venue: Venue
    market_id: str
    title: str
    outcomes: list[str] = Field(default_factory=list)
    url: str | None = None
    status: str | None = None
    closes_at: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OrderBook(BaseModel):
    """Normalized order book snapshot for a market."""

    market_id: str
    bids: list[tuple[Decimal, Decimal]] = Field(default_factory=list)
    asks: list[tuple[Decimal, Decimal]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class OrderRequest(BaseModel):
    """Venue-agnostic order request."""

    venue: Venue
    market_id: str
    outcome: str
    side: OrderSide
    price: Decimal
    size: Decimal
    order_type: OrderType = OrderType.LIMIT
    client_order_id: str | None = None


class OrderResult(BaseModel):
    """Normalized order placement response."""

    venue: Venue
    order_id: str
    status: str
    raw: dict[str, Any] = Field(default_factory=dict)


class Position(BaseModel):
    """Normalized open position."""

    venue: Venue
    market_id: str
    outcome: str
    size: Decimal
    average_price: Decimal | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PredictionMarketClientError(RuntimeError):
    """Base error for unified client failures."""


class BackendUnavailableError(PredictionMarketClientError):
    """Raised when no configured backend can service a client operation."""


class PredictionMarketClient:
    """Async facade over PMXT with direct SDK fallbacks.

    The concrete PMXT, Polymarket, and Kalshi APIs are isolated behind dynamic
    calls so tests can inject lightweight mock adapters without importing the
    external SDKs.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        pmxt_client: Any | None = None,
        polymarket_client: Any | None = None,
        kalshi_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._pmxt_client = pmxt_client
        self._polymarket_client = polymarket_client
        self._kalshi_client = kalshi_client
        self._http_client = http_client or httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds
        )
        self._owns_http_client = http_client is None

    async def __aenter__(self) -> PredictionMarketClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close owned network resources."""

        if self._owns_http_client:
            await self._http_client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, PredictionMarketClientError)),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=4),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def fetch_markets(self, venues: Sequence[Venue] | None = None) -> list[UnifiedMarket]:
        """Fetch active markets from PMXT first, then direct venue adapters."""

        target_venues = list(venues or [Venue.POLYMARKET, Venue.KALSHI])
        backends = await self._available_backends()

        for name, backend in backends:
            try:
                markets = await self._fetch_markets_from_backend(name, backend, target_venues)
            except Exception as exc:
                logger.warning("market_fetch_backend_failed", backend=name, error=str(exc))
                continue

            if markets:
                logger.info("markets_fetched", backend=name, count=len(markets))
                return markets

        raise BackendUnavailableError("No prediction market backend returned markets.")

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, PredictionMarketClientError)),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=4),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def fetch_order_book(self, market_id: str, venue: Venue | None = None) -> OrderBook:
        """Fetch a normalized order book snapshot."""

        for name, backend in await self._available_backends(venue):
            try:
                raw = await self._call_first_available(
                    backend,
                    ("fetch_order_book", "get_order_book", "order_book"),
                    market_id,
                )
                return self._normalize_order_book(market_id, raw)
            except Exception as exc:
                logger.warning("order_book_backend_failed", backend=name, error=str(exc))
                continue

        raise BackendUnavailableError(f"No backend could fetch order book for {market_id}.")

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, PredictionMarketClientError)),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=4),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Place an order through PMXT first, then direct venue adapter."""

        for name, backend in await self._available_backends(order.venue):
            try:
                raw = await self._call_first_available(
                    backend,
                    ("place_order", "create_order", "submit_order"),
                    order.model_dump(mode="json"),
                )
                return self._normalize_order_result(order.venue, raw)
            except Exception as exc:
                logger.warning("place_order_backend_failed", backend=name, error=str(exc))
                continue

        raise BackendUnavailableError(f"No backend could place order on {order.venue}.")

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, PredictionMarketClientError)),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=4),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def get_positions(self, venue: Venue | None = None) -> list[Position]:
        """Fetch current positions from the best available backend."""

        for name, backend in await self._available_backends(venue):
            try:
                raw_positions = await self._call_first_available(
                    backend,
                    ("get_positions", "fetch_positions", "positions"),
                )
                positions = [self._normalize_position(item, venue) for item in raw_positions or []]
                logger.info("positions_fetched", backend=name, count=len(positions))
                return positions
            except Exception as exc:
                logger.warning("positions_backend_failed", backend=name, error=str(exc))
                continue

        raise BackendUnavailableError("No backend could fetch positions.")

    async def _available_backends(self, venue: Venue | None = None) -> list[tuple[str, Any]]:
        backends: list[tuple[str, Any]] = []

        pmxt_client = self._pmxt_client or self._load_pmxt_client()
        if pmxt_client is not None:
            self._pmxt_client = pmxt_client
            backends.append(("pmxt", pmxt_client))

        if venue in (None, Venue.POLYMARKET):
            polymarket_client = self._polymarket_client or self._load_polymarket_client()
            if polymarket_client is not None:
                self._polymarket_client = polymarket_client
                backends.append(("polymarket", polymarket_client))

        if venue in (None, Venue.KALSHI):
            kalshi_client = self._kalshi_client or self._load_kalshi_client()
            if kalshi_client is not None:
                self._kalshi_client = kalshi_client
                backends.append(("kalshi", kalshi_client))

        return backends

    def _load_pmxt_client(self) -> Any | None:
        return self._load_first_client(
            module_names=("pmxt",),
            class_names=("AsyncClient", "Client", "PMXTClient"),
            kwargs={
                "polymarket_api_key": self.settings.polymarket_api_key,
                "kalshi_api_key": self.settings.kalshi_api_key,
                "kalshi_api_secret": self.settings.kalshi_api_secret,
            },
        )

    def _load_polymarket_client(self) -> Any | None:
        return self._load_first_client(
            module_names=("py_clob_client_v2", "py_clob_client.client"),
            class_names=("AsyncClient", "ClobClient", "Client", "PolymarketClient"),
            kwargs={
                "host": self.settings.polymarket_base_url,
                "key": self.settings.polymarket_api_key,
            },
        )

    def _load_kalshi_client(self) -> Any | None:
        return self._load_first_client(
            module_names=("kalshi", "kalshi_python"),
            class_names=("AsyncClient", "Client", "KalshiClient"),
            kwargs={
                "api_key": self.settings.kalshi_api_key,
                "api_secret": self.settings.kalshi_api_secret,
            },
        )

    def _load_first_client(
        self,
        *,
        module_names: Sequence[str],
        class_names: Sequence[str],
        kwargs: dict[str, Any],
    ) -> Any | None:
        clean_kwargs = {key: self._secret_value(value) for key, value in kwargs.items() if value}

        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue

            for class_name in class_names:
                client_cls = getattr(module, class_name, None)
                if client_cls is None:
                    continue

                try:
                    return client_cls(**clean_kwargs)
                except TypeError:
                    try:
                        return client_cls()
                    except Exception as exc:
                        logger.debug(
                            "client_init_failed",
                            module=module_name,
                            class_name=class_name,
                            error=str(exc),
                        )
                except Exception as exc:
                    logger.debug(
                        "client_init_failed",
                        module=module_name,
                        class_name=class_name,
                        error=str(exc),
                    )

        return None

    async def _fetch_markets_from_backend(
        self,
        backend_name: str,
        backend: Any,
        venues: Sequence[Venue],
    ) -> list[UnifiedMarket]:
        raw = await self._call_first_available(
            backend,
            ("fetch_markets", "list_markets", "get_markets", "markets"),
            venues=[venue.value for venue in venues],
        )
        if raw is None:
            return []

        return [
            self._normalize_market(item, default_venue=self._venue_from_backend_name(backend_name))
            for item in raw
        ]

    async def _call_first_available(
        self,
        backend: Any,
        method_names: Sequence[str],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        for method_name in method_names:
            method = getattr(backend, method_name, None)
            if method is None:
                continue

            return await self._call_maybe_async(method, *args, **kwargs)

        raise BackendUnavailableError(
            f"Backend {type(backend).__name__} has none of: {', '.join(method_names)}"
        )

    async def _call_maybe_async(
        self,
        func: Callable[..., Any] | Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        try:
            result = func(*args, **kwargs)
        except TypeError:
            result = func(*args)

        if inspect.isawaitable(result):
            return await result
        return result

    def _normalize_market(self, raw: Any, default_venue: Venue) -> UnifiedMarket:
        data = self._as_dict(raw)
        venue = self._coerce_venue(data.get("venue") or data.get("exchange"), default_venue)
        market_id = str(data.get("market_id") or data.get("id") or data.get("ticker") or "")
        title = str(data.get("title") or data.get("question") or data.get("name") or market_id)
        outcomes = data.get("outcomes") or data.get("tokens") or []

        return UnifiedMarket(
            venue=venue,
            market_id=market_id,
            title=title,
            outcomes=[str(item) for item in outcomes],
            url=data.get("url"),
            status=data.get("status"),
            closes_at=data.get("closes_at") or data.get("close_time") or data.get("expiration"),
            raw=data,
        )

    def _normalize_order_book(self, market_id: str, raw: Any) -> OrderBook:
        data = self._as_dict(raw)
        return OrderBook(
            market_id=market_id,
            bids=self._normalize_levels(data.get("bids", [])),
            asks=self._normalize_levels(data.get("asks", [])),
            raw=data,
        )

    def _normalize_order_result(self, venue: Venue, raw: Any) -> OrderResult:
        data = self._as_dict(raw)
        order_id = str(data.get("order_id") or data.get("id") or data.get("client_order_id") or "")
        status = str(data.get("status") or "submitted")
        return OrderResult(venue=venue, order_id=order_id, status=status, raw=data)

    def _normalize_position(self, raw: Any, default_venue: Venue | None) -> Position:
        data = self._as_dict(raw)
        venue = self._coerce_venue(data.get("venue") or data.get("exchange"), default_venue)
        return Position(
            venue=venue,
            market_id=str(data.get("market_id") or data.get("id") or ""),
            outcome=str(data.get("outcome") or data.get("side") or ""),
            size=Decimal(str(data.get("size") or data.get("quantity") or "0")),
            average_price=self._optional_decimal(
                data.get("average_price") or data.get("avg_price")
            ),
            raw=data,
        )

    def _normalize_levels(self, raw_levels: Any) -> list[tuple[Decimal, Decimal]]:
        levels: list[tuple[Decimal, Decimal]] = []
        for level in raw_levels or []:
            if isinstance(level, dict):
                price = level.get("price")
                size = level.get("size") or level.get("quantity")
            else:
                price, size = level[0], level[1]
            levels.append((Decimal(str(price)), Decimal(str(size))))
        return levels

    def _as_dict(self, raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, BaseModel):
            return cast(dict[str, Any], raw.model_dump())
        if isinstance(raw, dict):
            return raw
        if hasattr(raw, "dict"):
            return cast(dict[str, Any], raw.dict())
        return {
            name: getattr(raw, name)
            for name in dir(raw)
            if not name.startswith("_") and not callable(getattr(raw, name))
        }

    def _venue_from_backend_name(self, backend_name: str) -> Venue:
        if backend_name == "kalshi":
            return Venue.KALSHI
        return Venue.POLYMARKET

    def _coerce_venue(self, value: Any, default: Venue | None) -> Venue:
        if isinstance(value, Venue):
            return value
        if value:
            try:
                return Venue(str(value).lower())
            except ValueError:
                pass
        return default or Venue.POLYMARKET

    def _optional_decimal(self, value: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    def _secret_value(self, value: Any) -> Any:
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        return value


# Backward-compatible aliases for the initial scaffold.
Market = UnifiedMarket
Side = OrderSide
