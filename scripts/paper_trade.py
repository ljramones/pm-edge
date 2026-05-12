"""Run paper trading simulations."""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from core import OrderRequest, OrderSide, Venue, get_settings
from execution import PaperTradingConfig, PaperTradingEngine
from utils import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit a deterministic paper order.")
    parser.add_argument(
        "--venue",
        choices=[venue.value for venue in Venue],
        default=Venue.POLYMARKET.value,
    )
    parser.add_argument("--market-id", default="demo-market")
    parser.add_argument("--outcome", default="Yes")
    parser.add_argument(
        "--side",
        choices=[side.value for side in OrderSide],
        default=OrderSide.BUY.value,
    )
    parser.add_argument("--price", type=Decimal, default=Decimal("0.50"))
    parser.add_argument("--size", type=Decimal, default=Decimal("1"))
    parser.add_argument("--starting-cash", type=Decimal, default=Decimal("10000"))
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    engine = PaperTradingEngine(
        PaperTradingConfig(
            starting_cash=args.starting_cash,
            max_order_notional=Decimal(str(settings.max_order_notional_usd)),
            max_portfolio_notional=Decimal(str(settings.max_portfolio_notional_usd)),
        )
    )
    result = await engine.place_order(
        OrderRequest(
            venue=Venue(args.venue),
            market_id=args.market_id,
            outcome=args.outcome,
            side=OrderSide(args.side),
            price=args.price,
            size=args.size,
        )
    )
    print(f"Paper order {result.order_id} {result.status}; cash={engine.cash}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
