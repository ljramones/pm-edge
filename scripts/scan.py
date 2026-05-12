"""Scan markets for candidate opportunities."""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from core import BackendUnavailableError, MarketScanner, PredictionMarketClient, Venue, get_settings
from utils import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan prediction markets for Phase 0 opportunities."
    )
    parser.add_argument("--min-edge-bps", type=Decimal, default=Decimal("25"))
    parser.add_argument("--venue", choices=[venue.value for venue in Venue], action="append")
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    venues = [Venue(value) for value in args.venue] if args.venue else None
    async with PredictionMarketClient(settings=settings) as client:
        scanner = MarketScanner(client, min_edge_bps=args.min_edge_bps)
        try:
            result = await scanner.scan_once(venues)
        except BackendUnavailableError as exc:
            print(f"Scan unavailable: {exc}")
            return 2

    print(
        f"Scanned {len(result.snapshots)} market snapshots; "
        f"found {len(result.opportunities)} opportunities."
    )
    for opportunity in result.opportunities[: args.limit]:
        print(
            f"{opportunity.edge_bps} bps | {opportunity.title} / {opportunity.outcome}: "
            f"buy {opportunity.buy_venue.value} @{opportunity.buy_price}, "
            f"sell {opportunity.sell_venue.value} @{opportunity.sell_price}"
        )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
