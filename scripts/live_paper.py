"""Run the live paper trading loop."""

from __future__ import annotations

import argparse
import asyncio
import signal
from pathlib import Path
from typing import cast

from core import get_settings
from data.llm_news_processor import LLMProvider
from execution import PaperTrader, PaperTraderConfig
from utils import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live paper trading with monitoring state.")
    parser.add_argument("--interval", type=int, default=None)
    parser.add_argument("--kelly-fraction", type=float, default=0.35)
    parser.add_argument("--max-exposure", type=float, default=0.25)
    parser.add_argument("--max-position-weight", type=float, default=0.05)
    parser.add_argument("--review-threshold", type=float, default=None)
    parser.add_argument("--review-timeout", type=int, default=None)
    parser.add_argument("--no-review", action="store_true")
    parser.add_argument("--virtual-capital", type=float, default=None)
    parser.add_argument("--min-volume", type=float, default=None)
    parser.add_argument("--max-markets", type=int, default=None)
    parser.add_argument("--state-path", type=Path, default=None)
    parser.add_argument("--audit-log-path", type=Path, default=None)
    parser.add_argument("--review-flag-path", type=Path, default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--use-onchain", action="store_true")
    parser.add_argument("--crypto-only", action="store_true")
    parser.add_argument("--min-edge", type=float, default=0.08)
    parser.add_argument("--adverse-buffer", type=float, default=0.25)
    parser.add_argument("--max-tail-exposure", type=float, default=0.06)
    parser.add_argument(
        "--mode",
        choices=["directional", "liquidity-only"],
        default="directional",
        help="Paper trading strategy mode. liquidity-only disables directional edge betting.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["ollama", "openai", "claude", "grok"],
        default=None,
    )
    parser.add_argument("--ollama", action="store_true", help="Use local Ollama for LLM features.")
    parser.add_argument("--articles-per-market", type=int, default=6)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit. Useful for smoke tests and cron.",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    config = PaperTraderConfig(
        interval_seconds=args.interval or settings.paper_trader_interval_seconds,
        virtual_capital=args.virtual_capital or settings.paper_trader_virtual_capital_usd,
        min_volume=(
            args.min_volume if args.min_volume is not None else settings.paper_trader_min_volume_usd
        ),
        max_markets=args.max_markets or settings.paper_trader_max_markets,
        kelly_fraction=args.kelly_fraction,
        max_exposure=args.max_exposure,
        max_position_weight=args.max_position_weight,
        review_mode=(not args.no_review) and settings.paper_trader_review_mode,
        review_threshold=(
            args.review_threshold
            if args.review_threshold is not None
            else settings.paper_trader_review_threshold
        ),
        review_timeout_seconds=(
            args.review_timeout
            if args.review_timeout is not None
            else settings.paper_trader_review_timeout_seconds
        ),
        review_flag_path=args.review_flag_path or settings.paper_trader_review_flag_path,
        state_path=args.state_path or settings.paper_trader_state_path,
        audit_log_path=args.audit_log_path or settings.paper_trader_audit_log_path,
        use_advanced_features=settings.use_advanced_features or args.use_llm or args.use_onchain,
        use_llm=args.use_llm,
        use_onchain=args.use_onchain,
        crypto_only=args.crypto_only,
        llm_provider=cast(
            LLMProvider,
            "ollama" if args.ollama else args.llm_provider or settings.llm_provider,
        ),
        articles_per_market=args.articles_per_market,
        mode=args.mode,
        liquidity_min_edge=args.min_edge,
        liquidity_adverse_buffer=args.adverse_buffer,
        liquidity_max_tail_exposure=args.max_tail_exposure,
    )
    trader = PaperTrader(config=config, settings=settings)
    try:
        if args.once:
            result = await trader.run_once()
            print(
                "paper cycle complete: "
                f"markets={result.market_count} signals={result.signal_count} "
                f"targets={result.target_count} equity={result.equity:.2f}"
            )
            return 0

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await trader.run_forever(stop_event)
        print("paper trader stopped gracefully")
        return 0
    finally:
        await trader.close()


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
