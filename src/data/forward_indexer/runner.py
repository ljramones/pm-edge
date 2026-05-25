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
from datetime import UTC, datetime, timedelta
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

# Distinct tag for hi-cad near-resolution snapshots. MUST match the literal that
# scripts/experiment_02_capture_rate.py filters on (its HICAD_SOURCE constant);
# without an exact match the experiment's data cannot be isolated.
NEAR_RESOLUTION_SOURCE = "near_resolution_hicad"
# Venues eligible for hi-cad capture. Kalshi only: it has reliable close times and
# is the frozen-pre-resolution venue (Entry 23). Polymarket is excluded — its
# capture-to-resolution lag (~16h median) means near-close books are too stale to
# be worth the extra write volume.
NEAR_RESOLUTION_VENUES = ("kalshi",)
# How long after the close timestamp to keep capturing (catch the resolution snap).
NEAR_RESOLUTION_GRACE_SECONDS = 300.0
# Throttle the shed warning so a sustained memory crisis does not spam the journal.
_SHED_LOG_INTERVAL_SECONDS = 30.0


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
    # Experiment 2 — high-cadence near-resolution capture (OFF by default).
    near_resolution_capture_enabled: bool = False
    near_resolution_window_seconds: float = 1800.0
    near_resolution_cadence_seconds: float = 2.0
    near_resolution_max_markets: int = 30
    near_resolution_grace_seconds: float = NEAR_RESOLUTION_GRACE_SECONDS


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
        self._near_resolution_active = 0
        self._last_shed_log_at: datetime | None = None

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
            if self.config.near_resolution_capture_enabled:
                self._main_tasks.append(asyncio.create_task(self._near_resolution_loop()))
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

        # When hi-cad near-resolution capture is enabled, keep markets tracked all
        # the way to close so their books stay warm for the final window — the
        # normal `min_time_to_close_hours` filter would otherwise drop them ~2h out,
        # long before the near-resolution window opens, and the feature would have
        # nothing to capture. Gated behind the flag, so flag-OFF behaviour is
        # identical to before.
        min_time_to_close_hours = (
            0.0
            if self.config.near_resolution_capture_enabled
            else self.config.min_time_to_close_hours
        )
        thresholds = ActivityThresholds(
            min_24h_volume_usd=self.config.min_24h_volume_usd,
            max_spread_cents=self.config.max_spread_cents,
            max_last_trade_age_hours=self.config.max_last_trade_age_hours,
            min_market_age_minutes=self.config.min_market_age_minutes,
            min_time_to_close_hours=min_time_to_close_hours,
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

    async def _near_resolution_loop(self) -> None:
        while not self._stop.is_set():
            await self.capture_near_resolution_once()
            if await self._sleep_or_stop(self.config.near_resolution_cadence_seconds):
                break

    async def capture_near_resolution_once(self) -> int:
        """Capture one hi-cad batch for near-close markets; dedup bypassed.

        Returns the number of snapshots written. Sheds (writes nothing) when
        process memory is over the ceiling, so this mode can never be the thing
        that OOM-kills the box.
        """

        now = datetime.now(tz=UTC)
        selected = self._select_near_resolution_markets(now=now, memory_mb=current_memory_mb())
        self._near_resolution_active = len(selected)
        if not selected:
            return 0
        rows: list[dict[str, Any]] = []
        for indexer, market in selected:
            state = await indexer.current_book_state(market.market_id)
            if state is None:
                continue
            row = await state.snapshot(timestamp=now)
            row["snapshot_source"] = NEAR_RESOLUTION_SOURCE
            rows.append(row)
        if not rows:
            return 0
        accepted = await self.writer.add_records(
            TableName.ORDER_BOOK_SNAPSHOTS, rows, bypass_dedup=True
        )
        self._snapshots_written += accepted
        return accepted

    def _select_near_resolution_markets(
        self, *, now: datetime, memory_mb: float
    ) -> list[tuple[VenueIndexer, MarketDescriptor]]:
        """Return up to ``max_markets`` soonest-closing in-window markets.

        Shed to empty when memory is over the ceiling. The hard cap is always
        enforced, so concurrent hi-cad markets never exceed ``max_markets``.
        """

        if memory_mb > self.config.max_memory_mb:
            self._log_shed(memory_mb=memory_mb, now=now)
            return []

        window = timedelta(seconds=self.config.near_resolution_window_seconds)
        grace = timedelta(seconds=self.config.near_resolution_grace_seconds)
        candidates: list[tuple[datetime, VenueIndexer, MarketDescriptor]] = []
        for indexer in self.indexers:
            if indexer.venue not in NEAR_RESOLUTION_VENUES:
                continue
            for market in self._tracked_markets.get(indexer.venue, []):
                if market.end_date is None:
                    continue
                close_ts = _to_utc(market.end_date)
                if close_ts - window <= now < close_ts + grace:
                    candidates.append((close_ts, indexer, market))
        candidates.sort(key=lambda item: item[0])  # soonest-closing first
        capped = candidates[: self.config.near_resolution_max_markets]
        return [(indexer, market) for _, indexer, market in capped]

    def _log_shed(self, *, memory_mb: float, now: datetime) -> None:
        if (
            self._last_shed_log_at is not None
            and (now - self._last_shed_log_at).total_seconds() < _SHED_LOG_INTERVAL_SECONDS
        ):
            return
        self._last_shed_log_at = now
        self._logger.warning(
            "forward_indexer_near_resolution_shed",
            memory_mb=round(memory_mb, 2),
            max_memory_mb=self.config.max_memory_mb,
            reason="memory_ceiling_exceeded",
        )

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
                near_resolution_markets_active=self._near_resolution_active,
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


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


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
