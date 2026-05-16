"""Forward-indexer orchestration loop."""

from __future__ import annotations

import asyncio
import gc
import json
import os
import signal
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from utils.logging import get_logger

from .base import MarketDescriptor, VenueIndexer
from .filters import (
    ActivityThresholds,
    activity_filter_rejection_reason,
    empty_rejection_counts,
)
from .schemas import MARKET_METADATA_SCHEMA_VERSION, TableName
from .storage import BufferedParquetWriter


@dataclass(frozen=True)
class RunnerConfig:
    """Runtime controls for the forward indexer."""

    emit_cadence_seconds: float = 15.0
    discovery_cadence_seconds: float = 1800.0
    book_depth_levels: int = 5
    min_24h_volume_usd: float = 10_000.0
    max_spread_cents: float = 10.0
    max_last_trade_age_hours: float = 24.0
    min_market_age_minutes: float = 30.0
    min_time_to_close_hours: float = 2.0
    max_tracked_markets_per_venue: int = 500
    output_dir: Path = Path("data/raw/forward_index")
    max_memory_mb: float = 1024.0
    polling_mode: bool = False
    dry_run: bool = False
    heartbeat_seconds: float = 60.0


class IndexerRunner:
    """Coordinate discovery, venue subscriptions, periodic snapshots, and flushing."""

    def __init__(
        self,
        *,
        config: RunnerConfig,
        indexers: list[VenueIndexer],
        writer: BufferedParquetWriter | None = None,
    ) -> None:
        self.config = config
        self.indexers = indexers
        self.writer = writer or BufferedParquetWriter(config.output_dir)
        self._logger = get_logger(__name__)
        self._stop = asyncio.Event()
        self._tracked_markets: dict[str, list[MarketDescriptor]] = {}
        self._subscription_tasks: list[asyncio.Task[None]] = []
        self._main_tasks: list[asyncio.Task[None]] = []
        self._run_task: asyncio.Task[None] | None = None
        self._snapshots_written = 0
        self._last_heartbeat_snapshots = 0
        self._last_heartbeat_at = datetime.now(tz=UTC)

    async def run(self) -> None:
        """Run until cancelled or stopped by signal."""

        self._run_task = asyncio.current_task()
        with suppress(asyncio.CancelledError):
            self._install_signal_handlers()
            await self.writer.load_existing_keys_for_today()
            await self.discover_once()
            if self.config.dry_run:
                self._log_dry_run_plan()
                return
            await self._start_subscriptions()
            self._main_tasks = [
                asyncio.create_task(self._discovery_loop()),
                asyncio.create_task(self._emit_loop()),
                asyncio.create_task(self._heartbeat_loop()),
            ]
            await asyncio.gather(*self._main_tasks)

    async def stop(self) -> None:
        """Request graceful shutdown and flush buffers."""

        self._stop.set()
        current_task = asyncio.current_task()
        for task in self._subscription_tasks:
            task.cancel()
        for task in self._main_tasks:
            task.cancel()
        if (
            self._run_task is not None
            and self._run_task is not current_task
            and not self._run_task.done()
        ):
            self._run_task.cancel()
        await asyncio.gather(*(indexer.flush_pending() for indexer in self.indexers))
        await self.writer.flush()

    async def discover_once(self) -> None:
        """Run one discovery cycle and capture metadata snapshots."""

        thresholds = ActivityThresholds(
            min_24h_volume_usd=self.config.min_24h_volume_usd,
            max_spread_cents=self.config.max_spread_cents,
            max_last_trade_age_hours=self.config.max_last_trade_age_hours,
            min_market_age_minutes=self.config.min_market_age_minutes,
            min_time_to_close_hours=self.config.min_time_to_close_hours,
        )
        captured_at = datetime.now(tz=UTC)
        previous_tracked = {
            venue: {market.market_id: market for market in markets}
            for venue, markets in self._tracked_markets.items()
        }
        discovered = await asyncio.gather(
            *(indexer.discover_markets() for indexer in self.indexers)
        )
        for indexer, markets in zip(self.indexers, discovered, strict=True):
            tracked = []
            rejection_counts = empty_rejection_counts()
            for market in markets:
                rejection_reason = activity_filter_rejection_reason(
                    volume_24h=market.volume_24h,
                    spread=market.spread,
                    last_trade_at=market.last_trade_at,
                    created_at=market.created_at,
                    end_date=market.end_date,
                    thresholds=thresholds,
                    now=captured_at,
                )
                if rejection_reason is None:
                    tracked.append(market)
                else:
                    rejection_counts[rejection_reason] += 1
            tracked_candidates = len(tracked)
            tracked = ranked_markets(tracked)[: self.config.max_tracked_markets_per_venue]
            final_metadata_markets = await _final_metadata_before_drop(
                indexer=indexer,
                previous_tracked=previous_tracked.get(indexer.venue, {}),
                discovered=markets,
                tracked=tracked,
            )
            self._tracked_markets[indexer.venue] = tracked
            if not self.config.dry_run:
                metadata_markets = tracked + final_metadata_markets
                for chunk in _chunks(metadata_markets, 1_000):
                    metadata_rows = [
                        metadata_record(market, captured_at=captured_at) for market in chunk
                    ]
                    await self.writer.add_records(
                        TableName.MARKET_METADATA_SNAPSHOTS, metadata_rows
                    )
                await self.writer.flush()
            self._logger.info(
                "forward_indexer_discovery",
                venue=indexer.venue,
                discovered=len(markets),
                tracked_candidates=tracked_candidates,
                tracked=len(tracked),
                max_tracked_markets_per_venue=self.config.max_tracked_markets_per_venue,
                filter_rejection_reasons=rejection_counts,
                **rejection_counts,
            )
            markets.clear()
        del discovered
        gc.collect()

    async def emit_once(self) -> int:
        """Emit one snapshot batch from current in-memory book state."""

        now = datetime.now(tz=UTC)
        rows: list[dict[str, Any]] = []
        for indexer in self.indexers:
            if self.config.polling_mode:
                await self._refresh_polling_books(indexer)
            for market in self._tracked_markets.get(indexer.venue, []):
                state = await indexer.current_book_state(market.market_id)
                if state is not None:
                    rows.append(await state.snapshot(timestamp=now))
        if rows:
            accepted = await self.writer.add_records(TableName.ORDER_BOOK_SNAPSHOTS, rows)
            self._snapshots_written += accepted
            await self._drain_trade_buffers()
            return accepted
        await self._drain_trade_buffers()
        return 0

    async def _drain_trade_buffers(self) -> None:
        trade_rows: list[dict[str, Any]] = []
        for indexer in self.indexers:
            drain = getattr(indexer, "drain_trade_events", None)
            if drain is not None:
                trade_rows.extend(await drain())
        if trade_rows:
            await self.writer.add_records(TableName.TRADE_EVENTS, trade_rows)

    async def _refresh_polling_books(self, indexer: VenueIndexer) -> None:
        refresh = getattr(indexer, "refresh_book", None)
        if refresh is None:
            return
        for market in self._tracked_markets.get(indexer.venue, []):
            await refresh(market)

    async def _start_subscriptions(self) -> None:
        if self.config.polling_mode:
            return
        for indexer in self.indexers:
            markets = self._tracked_markets.get(indexer.venue, [])
            if not markets:
                continue
            self._subscription_tasks.append(asyncio.create_task(indexer.subscribe_books(markets)))
            self._subscription_tasks.append(asyncio.create_task(indexer.subscribe_trades(markets)))

    async def _discovery_loop(self) -> None:
        while not self._stop.is_set():
            if await self._sleep_or_stop(self.config.discovery_cadence_seconds):
                break
            await self.discover_once()

    async def _emit_loop(self) -> None:
        while not self._stop.is_set():
            await self.emit_once()
            memory_mb = current_memory_mb()
            if memory_mb > self.config.max_memory_mb:
                self._logger.warning(
                    "forward_indexer_memory_ceiling_exceeded",
                    memory_mb=memory_mb,
                    max_memory_mb=self.config.max_memory_mb,
                    dedupe_keys_retained=self.writer.seen_key_count,
                )
                await self.writer.flush()
            if await self._sleep_or_stop(self.config.emit_cadence_seconds):
                break

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            if await self._sleep_or_stop(self.config.heartbeat_seconds):
                break
            now = datetime.now(tz=UTC)
            elapsed = max((now - self._last_heartbeat_at).total_seconds(), 1.0)
            delta = self._snapshots_written - self._last_heartbeat_snapshots
            self._logger.info(
                "forward_indexer_heartbeat",
                snapshots_per_second=round(delta / elapsed, 4),
                snapshots_written_total=self._snapshots_written,
                markets_tracked=sum(len(markets) for markets in self._tracked_markets.values()),
                websocket_connections=sum(
                    item.stats().websocket_connections for item in self.indexers
                ),
                memory_mb=round(current_memory_mb(), 2),
                dedupe_keys_retained=self.writer.seen_key_count,
                errors_since_last_heartbeat=sum(
                    item.stats().errors_since_heartbeat for item in self.indexers
                ),
            )
            for indexer in self.indexers:
                indexer.stats().errors_since_heartbeat = 0
            self._last_heartbeat_snapshots = self._snapshots_written
            self._last_heartbeat_at = now

    async def _sleep_or_stop(self, seconds: float) -> bool:
        """Sleep up to ``seconds`` or return early when stop is signalled.

        Returns True if stop was signalled, False if the full duration elapsed.
        """

        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except TimeoutError:
            return False

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

    def _log_dry_run_plan(self) -> None:
        for venue, markets in self._tracked_markets.items():
            self._logger.info(
                "forward_indexer_dry_run_plan",
                venue=venue,
                tracked_markets=len(markets),
                output_dir=str(self.config.output_dir),
            )


def metadata_record(market: MarketDescriptor, *, captured_at: datetime) -> dict[str, Any]:
    """Return a parquet-ready metadata snapshot row."""

    return {
        "schema_version": MARKET_METADATA_SCHEMA_VERSION,
        "venue": market.venue,
        "market_id": market.market_id,
        "captured_at_utc": captured_at,
        "status": market.status,
        "volume_24h": market.volume_24h,
        "liquidity": market.liquidity,
        "end_date": market.end_date,
        "venue_status_raw": market.venue_status_raw,
        "is_closed": market.is_closed,
        "is_archived": market.is_archived,
        "is_resolved": market.is_resolved,
        "resolution_outcome": market.resolution_outcome,
        "resolution_timestamp_utc": market.resolution_timestamp_utc,
        "accepting_orders": market.accepting_orders,
        "raw_json": json.dumps(market.raw, default=str, sort_keys=True),
    }


def ranked_markets(markets: list[MarketDescriptor]) -> list[MarketDescriptor]:
    """Rank subscription candidates by liquidity usefulness."""

    return sorted(
        markets,
        key=lambda market: (
            market.volume_24h or 0.0,
            market.liquidity or 0.0,
            -(market.spread if market.spread is not None else 1.0),
        ),
        reverse=True,
    )


async def _final_metadata_before_drop(
    *,
    indexer: VenueIndexer,
    previous_tracked: dict[str, MarketDescriptor],
    discovered: list[MarketDescriptor],
    tracked: list[MarketDescriptor],
) -> list[MarketDescriptor]:
    """Return one terminal metadata snapshot for markets leaving the tracked set."""

    tracked_ids = {market.market_id for market in tracked}
    final_markets: dict[str, MarketDescriptor] = {}
    for market in discovered:
        if market.market_id not in tracked_ids and _is_terminal_market(market):
            final_markets[market.market_id] = market

    discovered_ids = {market.market_id for market in discovered}
    fetch = getattr(indexer, "fetch_market_metadata", None)
    if fetch is not None:
        for market_id, market in previous_tracked.items():
            if market_id in tracked_ids or market_id in discovered_ids:
                continue
            refreshed = await fetch(market)
            if refreshed is not None and _is_terminal_market(refreshed):
                final_markets[market_id] = refreshed
    return list(final_markets.values())


def _is_terminal_market(market: MarketDescriptor) -> bool:
    return market.is_closed is True or market.is_resolved is True


def _chunks(markets: list[MarketDescriptor], size: int) -> list[list[MarketDescriptor]]:
    return [markets[index : index + size] for index in range(0, len(markets), size)]


def current_memory_mb() -> float:
    """Return current process RSS memory in MB."""

    try:
        output = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return int(output.strip()) / 1024
    except Exception:
        pass

    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux reports KiB.
        if usage > 10_000_000:
            return usage / (1024 * 1024)
        return usage / 1024
    except Exception:
        return 0.0
