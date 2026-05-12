"""Market scanning and simple cross-venue arbitrage detection."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from collections.abc import AsyncIterator
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from core.client import OrderBook, PredictionMarketClient, UnifiedMarket, Venue
from utils.logging import get_logger

logger = get_logger(__name__)


class MarketSnapshot(BaseModel):
    """One market/outcome order book snapshot."""

    model_config = ConfigDict(frozen=True)

    venue: Venue
    market_id: str
    title: str
    outcome: str
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    url: str | None = None

    @property
    def mid(self) -> Decimal | None:
        """Return midpoint when both sides are available."""

        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / Decimal("2")

    @property
    def spread(self) -> Decimal | None:
        """Return bid/ask spread when both sides are available."""

        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid


class ArbitrageOpportunity(BaseModel):
    """Cross-venue buy-low/sell-high opportunity for the same outcome."""

    model_config = ConfigDict(frozen=True)

    title: str
    outcome: str
    buy_venue: Venue
    buy_market_id: str
    buy_price: Decimal
    sell_venue: Venue
    sell_market_id: str
    sell_price: Decimal
    edge: Decimal
    edge_bps: Decimal
    max_size: Decimal | None = None
    buy_url: str | None = None
    sell_url: str | None = None


class MarketScanResult(BaseModel):
    """Full output from one scanner pass."""

    snapshots: list[MarketSnapshot] = Field(default_factory=list)
    opportunities: list[ArbitrageOpportunity] = Field(default_factory=list)


class MarketScanner:
    """Fetch live market snapshots and identify simple arbitrage candidates."""

    def __init__(
        self,
        client: PredictionMarketClient,
        *,
        min_edge_bps: Decimal = Decimal("25"),
        max_concurrency: int = 10,
    ) -> None:
        self.client = client
        self.min_edge_bps = min_edge_bps
        self.max_concurrency = max_concurrency

    async def scan_once(self, venues: list[Venue] | None = None) -> MarketScanResult:
        """Run one market scan and return snapshots plus opportunities."""

        markets = await self.client.fetch_markets(venues)
        snapshots = await self._fetch_snapshots(markets)
        opportunities = detect_cross_venue_arbitrage(
            snapshots,
            min_edge_bps=self.min_edge_bps,
        )
        logger.info(
            "market_scan_completed",
            markets=len(markets),
            snapshots=len(snapshots),
            opportunities=len(opportunities),
        )
        return MarketScanResult(snapshots=snapshots, opportunities=opportunities)

    async def stream(
        self,
        *,
        interval_seconds: float = 30.0,
        venues: list[Venue] | None = None,
    ) -> AsyncIterator[MarketScanResult]:
        """Yield scan results forever at a fixed interval."""

        while True:
            yield await self.scan_once(venues)
            await asyncio.sleep(interval_seconds)

    async def _fetch_snapshots(self, markets: list[UnifiedMarket]) -> list[MarketSnapshot]:
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def fetch_one(market: UnifiedMarket) -> list[MarketSnapshot]:
            async with semaphore:
                try:
                    order_book = await self.client.fetch_order_book(market.market_id, market.venue)
                except Exception as exc:
                    logger.warning(
                        "market_snapshot_failed",
                        venue=market.venue.value,
                        market_id=market.market_id,
                        error=str(exc),
                    )
                    return []
                return snapshots_from_order_book(market, order_book)

        results = await asyncio.gather(*(fetch_one(market) for market in markets))
        return [snapshot for group in results for snapshot in group]


def snapshots_from_order_book(
    market: UnifiedMarket,
    order_book: OrderBook,
) -> list[MarketSnapshot]:
    """Build outcome-level snapshots from a normalized order book.

    Phase 0 clients expose one normalized book per market. If an SDK later
    returns per-outcome books in `raw`, this helper can be extended without
    changing scanner callers.
    """

    outcome = market.outcomes[0] if market.outcomes else "Yes"
    best_bid, bid_size = _best_bid(order_book)
    best_ask, ask_size = _best_ask(order_book)
    return [
        MarketSnapshot(
            venue=market.venue,
            market_id=market.market_id,
            title=market.title,
            outcome=outcome,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            url=market.url,
        )
    ]


def detect_cross_venue_arbitrage(
    snapshots: list[MarketSnapshot],
    *,
    min_edge_bps: Decimal = Decimal("25"),
) -> list[ArbitrageOpportunity]:
    """Detect exact-title cross-venue buy-low/sell-high opportunities."""

    grouped: dict[tuple[str, str], list[MarketSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[(_market_key(snapshot.title), snapshot.outcome.lower())].append(snapshot)

    opportunities: list[ArbitrageOpportunity] = []
    for (_title_key, _outcome_key), candidates in grouped.items():
        for buy_candidate in candidates:
            if buy_candidate.best_ask is None:
                continue
            for sell_candidate in candidates:
                if sell_candidate.best_bid is None or sell_candidate.venue == buy_candidate.venue:
                    continue

                edge = sell_candidate.best_bid - buy_candidate.best_ask
                edge_bps = edge * Decimal("10000")
                if edge_bps < min_edge_bps:
                    continue

                max_size = _min_optional(buy_candidate.ask_size, sell_candidate.bid_size)
                opportunities.append(
                    ArbitrageOpportunity(
                        title=buy_candidate.title,
                        outcome=buy_candidate.outcome,
                        buy_venue=buy_candidate.venue,
                        buy_market_id=buy_candidate.market_id,
                        buy_price=buy_candidate.best_ask,
                        sell_venue=sell_candidate.venue,
                        sell_market_id=sell_candidate.market_id,
                        sell_price=sell_candidate.best_bid,
                        edge=edge,
                        edge_bps=edge_bps,
                        max_size=max_size,
                        buy_url=buy_candidate.url,
                        sell_url=sell_candidate.url,
                    )
                )

    return sorted(opportunities, key=lambda item: item.edge_bps, reverse=True)


def _best_bid(order_book: OrderBook) -> tuple[Decimal | None, Decimal | None]:
    if not order_book.bids:
        return None, None
    price, size = max(order_book.bids, key=lambda level: level[0])
    return price, size


def _best_ask(order_book: OrderBook) -> tuple[Decimal | None, Decimal | None]:
    if not order_book.asks:
        return None, None
    price, size = min(order_book.asks, key=lambda level: level[0])
    return price, size


def _market_key(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()


def _min_optional(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)
