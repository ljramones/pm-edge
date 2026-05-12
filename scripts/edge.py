"""Rank markets by Phase 1 edge scores."""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from core import PredictionMarketClient, Venue, get_settings
from features import FeatureStore
from strategies import EdgeDetector
from utils import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rank markets by model-vs-market edge.")
    parser.add_argument("--venue", choices=[venue.value for venue in Venue], action="append")
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    venues = [Venue(value) for value in args.venue] if args.venue else None

    async with PredictionMarketClient(settings=settings) as client:
        markets = await client.fetch_markets(venues)
        detector = EdgeDetector(FeatureStore(client=client))
        signals = await detector.rank_markets(markets[: args.limit])

    for signal in signals:
        edge_bps = Decimal(str(signal.edge)) * Decimal("10000")
        print(
            f"{edge_bps:.0f} bps | {signal.market_id} | "
            f"market={signal.market_prob:.3f} model={signal.model_prob:.3f} "
            f"confidence={signal.confidence:.2f}"
        )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
