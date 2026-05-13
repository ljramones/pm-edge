"""Backtest liquidity-providing opportunities and optionally alert Telegram."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pandas as pd

from core import get_settings
from monitoring import TelegramNotifier
from scripts.deep_backtest import load_signal_frame
from strategies import LiquidityProvider, LiquidityProviderConfig, backtest_liquidity
from utils import configure_logging, resolve_repo_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest liquidity providing strategy.")
    parser.add_argument("--signals", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/liquidity_backtest.parquet")
    )
    parser.add_argument("--min-spread", type=float, default=0.03)
    parser.add_argument("--max-adverse-selection", type=float, default=0.45)
    parser.add_argument("--max-notional", type=float, default=50.0)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--notify", action="store_true")
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    if args.signals is not None:
        args.signals = resolve_repo_path(args.signals)
    args.output = resolve_repo_path(args.output)
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    frame = load_signal_frame(args.signals, demo=args.demo or args.signals is None)
    frame = add_demo_liquidity_columns(frame)
    provider = LiquidityProvider(
        LiquidityProviderConfig(
            min_spread=args.min_spread,
            max_adverse_selection=args.max_adverse_selection,
            max_notional=args.max_notional,
        )
    )
    result = backtest_liquidity(frame, provider)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(args.output, index=False)
    quoted = result[result["should_quote"]] if not result.empty else pd.DataFrame()
    pnl = float(quoted["pnl"].sum()) if not quoted.empty else 0.0
    print(f"Liquidity backtest saved to {args.output}; quotes={len(quoted)} pnl={pnl:.2f}")
    if args.notify:
        notifier = TelegramNotifier(settings=settings)
        try:
            if not quoted.empty:
                top = quoted.sort_values("edge", ascending=False).iloc[0]
                await notifier.liquidity_opportunity(
                    market_id=str(top["market_id"]),
                    spread=float(top["spread"]),
                    incentive=float(top["incentive_score"]),
                    edge=float(top["edge"]),
                    link=str(top["link"]) if top.get("link") else None,
                )
        finally:
            await notifier.close()
    return 0


def add_demo_liquidity_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Ensure signal rows have liquidity-provider columns."""

    output = frame.copy()
    if "spread" not in output:
        output["spread"] = 0.025 + (output.index.to_series() % 4) * 0.01
    if "liquidity" not in output:
        output["liquidity"] = 100_000 + (output.index.to_series() % 5) * 25_000
    if "volume" not in output:
        output["volume"] = output["liquidity"] * (0.5 + (output.index.to_series() % 3) * 0.2)
    if "incentive" not in output:
        output["incentive"] = (output.index.to_series() % 3) * 2.0
    if "duration_hours" not in output:
        output["duration_hours"] = 12 + (output.index.to_series() % 4) * 6
    return output


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
