"""Run the forward public market-data indexer."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import httpx

from core.config import get_settings
from data.forward_indexer import BufferedParquetWriter, IndexerRunner, RunnerConfig
from data.forward_indexer.base import VenueIndexer
from data.forward_indexer.kalshi import KalshiIndexer
from data.forward_indexer.polymarket import PolymarketIndexer
from utils.logging import configure_logging


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues", default="polymarket,kalshi")
    parser.add_argument(
        "--emit-cadence-seconds",
        type=float,
        default=settings.forward_indexer_emit_cadence_seconds,
    )
    parser.add_argument(
        "--discovery-cadence-seconds",
        type=float,
        default=settings.forward_indexer_discovery_cadence_seconds,
    )
    parser.add_argument(
        "--book-depth-levels",
        type=int,
        default=settings.forward_indexer_book_depth_levels,
    )
    parser.add_argument(
        "--min-24h-volume-usd",
        type=float,
        default=settings.forward_indexer_min_24h_volume_usd,
    )
    parser.add_argument(
        "--max-spread-cents",
        type=float,
        default=settings.forward_indexer_max_spread_cents,
    )
    parser.add_argument(
        "--max-last-trade-age-hours",
        type=float,
        default=settings.forward_indexer_max_last_trade_age_hours,
    )
    parser.add_argument(
        "--min-market-age-minutes",
        type=float,
        default=settings.forward_indexer_min_market_age_minutes,
    )
    parser.add_argument(
        "--min-time-to-close-hours",
        type=float,
        default=settings.forward_indexer_min_time_to_close_hours,
    )
    parser.add_argument(
        "--max-tracked-markets-per-venue",
        type=int,
        default=settings.forward_indexer_max_tracked_markets_per_venue,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=settings.forward_indexer_output_dir,
    )
    parser.add_argument(
        "--max-memory-mb",
        type=float,
        default=settings.forward_indexer_max_memory_mb,
    )
    parser.add_argument(
        "--polling-mode",
        action="store_true",
        help="Diagnostic mode: disable WebSockets and poll REST books on the emit cadence.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover markets, print the plan, and write nothing.",
    )
    return parser.parse_args()


async def websocket_connect(url: str) -> Any:
    """Open a WebSocket connection using the optional websockets dependency."""

    import websockets

    return await websockets.connect(url, max_size=2**22, ping_interval=20, ping_timeout=20)


async def run() -> None:
    """Run the configured forward indexer."""

    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    args = parse_args()
    selected_venues = {venue.strip().lower() for venue in args.venues.split(",") if venue.strip()}
    client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    ws_connect = None if args.polling_mode else websocket_connect
    indexers: list[VenueIndexer] = []
    if "polymarket" in selected_venues:
        indexers.append(
            PolymarketIndexer(
                base_url=settings.polymarket_base_url,
                depth=args.book_depth_levels,
                client=client,
                ws_connect=ws_connect,
            )
        )
    if "kalshi" in selected_venues:
        indexers.append(
            KalshiIndexer(
                base_url=settings.kalshi_base_url,
                depth=args.book_depth_levels,
                client=client,
                ws_connect=ws_connect,
                request_delay_seconds=settings.kalshi_request_delay_seconds,
            )
        )
    config = RunnerConfig(
        emit_cadence_seconds=args.emit_cadence_seconds,
        discovery_cadence_seconds=args.discovery_cadence_seconds,
        book_depth_levels=args.book_depth_levels,
        min_24h_volume_usd=args.min_24h_volume_usd,
        max_spread_cents=args.max_spread_cents,
        max_last_trade_age_hours=args.max_last_trade_age_hours,
        min_market_age_minutes=args.min_market_age_minutes,
        min_time_to_close_hours=args.min_time_to_close_hours,
        max_tracked_markets_per_venue=args.max_tracked_markets_per_venue,
        output_dir=args.output_dir,
        max_memory_mb=args.max_memory_mb,
        polling_mode=args.polling_mode,
        dry_run=args.dry_run,
    )
    writer = BufferedParquetWriter(config.output_dir)
    runner = IndexerRunner(config=config, indexers=indexers, writer=writer)
    try:
        await runner.run()
    finally:
        await runner.stop()
        await client.aclose()


def main() -> None:
    """CLI entry point."""

    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
