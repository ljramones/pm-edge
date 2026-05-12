"""Generate reusable historical edge signal datasets."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

from core import BackendUnavailableError, PredictionMarketClient, Venue, get_settings
from features import FeatureStore
from strategies import EdgeDetector
from utils import configure_logging, get_logger

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate partitioned historical edge signals.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--interval-hours", type=int, default=6)
    parser.add_argument("--markets", choices=["all", "high-volume"], default="high-volume")
    parser.add_argument("--min-volume", type=float, default=500_000)
    parser.add_argument("--venue", choices=[venue.value for venue in Venue], action="append")
    parser.add_argument("--output", type=Path, default=Path("data/processed/signals"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--demo", action="store_true", help="Generate deterministic demo signals without APIs."
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    timestamps = list(iter_timestamps(args.start_date, args.end_date, args.interval_hours))
    if args.demo:
        write_demo_signals(timestamps, output=output, overwrite=args.overwrite)
        return 0

    venues = [Venue(value) for value in args.venue] if args.venue else None
    async with PredictionMarketClient(settings=settings) as client:
        detector = EdgeDetector(FeatureStore(client=client))
        for timestamp in tqdm(timestamps, desc="signals"):
            path = partition_path(output, timestamp)
            if path.exists() and not args.overwrite:
                continue
            try:
                markets = await client.fetch_markets(venues)
            except BackendUnavailableError as exc:
                logger.warning(
                    "signal_generation_skipped", as_of=timestamp.isoformat(), error=str(exc)
                )
                continue
            if args.markets == "high-volume":
                markets = [
                    market
                    for market in markets
                    if float(market.raw.get("volume", market.raw.get("liquidity", 0)) or 0)
                    >= args.min_volume
                ]
            rows: list[dict[str, Any]] = []
            for market in markets:
                try:
                    signal = await detector.score_market(market)
                except Exception as exc:
                    logger.warning(
                        "signal_generation_market_failed",
                        market_id=market.market_id,
                        error=str(exc),
                    )
                    continue
                rows.append(
                    {
                        "market_id": signal.market_id,
                        "as_of": timestamp,
                        "venue": market.venue.value,
                        "market_probability": signal.market_prob,
                        "model_probability": signal.model_prob,
                        "edge": signal.edge,
                        "confidence": signal.confidence,
                        "features": signal.features,
                        "reasoning": signal.reasoning,
                        "category": market.raw.get("category"),
                        "liquidity": market.raw.get("liquidity"),
                        "volume": market.raw.get("volume"),
                    }
                )
            write_partition(pd.DataFrame(rows), path)
    return 0


def iter_timestamps(start: str, end: str, interval_hours: int) -> list[datetime]:
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=UTC)
    interval = timedelta(hours=interval_hours)
    timestamps: list[datetime] = []
    cursor = start_dt
    while cursor <= end_dt:
        timestamps.append(cursor)
        cursor += interval
    return timestamps


def partition_path(root: Path, timestamp: datetime) -> Path:
    return root / f"date={timestamp.date().isoformat()}" / "signals.parquet"


def write_partition(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        frame = pd.DataFrame(
            columns=[
                "market_id",
                "as_of",
                "venue",
                "market_probability",
                "model_probability",
                "edge",
                "confidence",
            ]
        )
    frame.to_parquet(path, index=False)


def write_demo_signals(timestamps: list[datetime], *, output: Path, overwrite: bool) -> None:
    for index, timestamp in enumerate(tqdm(timestamps, desc="demo-signals")):
        path = partition_path(output, timestamp)
        if path.exists() and not overwrite:
            continue
        rows = [
            {
                "market_id": f"demo-{index}-{offset}",
                "as_of": timestamp,
                "resolved_at": timestamp + timedelta(days=14),
                "venue": "polymarket" if offset % 2 else "kalshi",
                "market_probability": 0.42 + offset * 0.02,
                "model_probability": 0.47 + offset * 0.02,
                "edge": 0.05,
                "confidence": 0.6,
                "liquidity": 750_000,
                "volume": 1_000_000,
                "category": "demo",
                "outcome": int((index + offset) % 3 != 0),
            }
            for offset in range(3)
        ]
        write_partition(pd.DataFrame(rows), path)


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
