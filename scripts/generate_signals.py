"""Generate reusable historical edge signal datasets."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pandas as pd
from tqdm import tqdm

from core import BackendUnavailableError, PredictionMarketClient, UnifiedMarket, Venue, get_settings
from data import LLMNewsProcessor, NewsSentimentEngine, OnChainProcessor
from data.llm_news_processor import LLMProvider
from data.onchain_processor import infer_asset_symbol
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
    parser.add_argument("--use-llm", action="store_true", help="Enable cached LLM news features.")
    parser.add_argument(
        "--use-onchain", action="store_true", help="Enable crypto on-chain feature snapshots."
    )
    parser.add_argument(
        "--llm-provider",
        choices=["openai", "claude", "grok"],
        default=None,
        help="LLM provider for advanced news summaries.",
    )
    parser.add_argument("--articles-per-market", type=int, default=6)
    parser.add_argument(
        "--crypto-only", action="store_true", help="Only score crypto-linked markets."
    )
    parser.add_argument(
        "--max-estimated-cost",
        type=float,
        default=None,
        help="Abort LLM generation when the estimated batch cost exceeds this value.",
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
        write_demo_signals(
            timestamps,
            output=output,
            overwrite=args.overwrite,
            include_advanced=args.use_llm or args.use_onchain,
        )
        return 0

    venues = [Venue(value) for value in args.venue] if args.venue else None
    llm_provider = cast(LLMProvider, args.llm_provider or settings.llm_provider)
    use_advanced = args.use_llm or args.use_onchain or settings.use_advanced_features
    news_engine = NewsSentimentEngine(settings=settings) if args.use_llm else None
    llm_processor = LLMNewsProcessor(settings=settings) if args.use_llm else None
    onchain_processor = OnChainProcessor(settings=settings) if args.use_onchain else None
    max_estimated_cost = (
        args.max_estimated_cost
        if args.max_estimated_cost is not None
        else settings.llm_max_batch_cost_usd
    )
    async with PredictionMarketClient(settings=settings) as client:
        detector = EdgeDetector(FeatureStore(client=client), use_advanced_features=use_advanced)
        try:
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
                if args.crypto_only:
                    markets = [
                        market for market in markets if infer_asset_symbol(market) is not None
                    ]
                if args.use_llm and llm_processor is not None:
                    estimate = llm_processor.estimate_batch_cost(
                        market_count=len(markets),
                        articles_per_market=args.articles_per_market,
                        provider=llm_provider,
                    )
                    logger.info(
                        "llm_signal_generation_cost_estimate",
                        as_of=timestamp.isoformat(),
                        market_count=len(markets),
                        estimated_cost_usd=estimate.estimated_cost_usd,
                        provider=estimate.provider,
                        model=estimate.model,
                        provider_credentials_configured=llm_processor.has_credentials(llm_provider),
                    )
                    if (
                        llm_processor.has_credentials(llm_provider)
                        and estimate.estimated_cost_usd > max_estimated_cost
                    ):
                        raise RuntimeError(
                            "Estimated LLM cost "
                            f"${estimate.estimated_cost_usd:.2f} exceeds limit "
                            f"${max_estimated_cost:.2f}. Increase --max-estimated-cost to proceed."
                        )

                rows: list[dict[str, Any]] = []
                for market in markets:
                    try:
                        context = await build_advanced_context(
                            market=market,
                            as_of=timestamp,
                            use_llm=args.use_llm,
                            use_onchain=args.use_onchain,
                            llm_provider=llm_provider,
                            articles_per_market=args.articles_per_market,
                            news_engine=news_engine,
                            llm_processor=llm_processor,
                            onchain_processor=onchain_processor,
                        )
                        signal = await detector.score_market(market, model_context=context)
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
                            "advanced_enabled": use_advanced,
                        }
                    )
                write_partition(pd.DataFrame(rows), path)
        finally:
            if news_engine is not None:
                await news_engine.close()
            if llm_processor is not None:
                await llm_processor.close()
            if onchain_processor is not None:
                await onchain_processor.close()
    return 0


async def build_advanced_context(
    *,
    market: UnifiedMarket,
    as_of: datetime,
    use_llm: bool,
    use_onchain: bool,
    llm_provider: LLMProvider,
    articles_per_market: int,
    news_engine: NewsSentimentEngine | None,
    llm_processor: LLMNewsProcessor | None,
    onchain_processor: OnChainProcessor | None,
) -> dict[str, Any]:
    """Build optional advanced signal context for one market."""

    context: dict[str, Any] = {"as_of": as_of}
    articles = []
    if use_llm and news_engine is not None and llm_processor is not None:
        try:
            fetched = await news_engine.fetch_gdelt(
                market.title, max_records=articles_per_market * 3
            )
            articles = [
                article
                for article in fetched
                if article.published_at <= as_of
                and article.published_at >= as_of - timedelta(days=7)
            ][:articles_per_market]
        except Exception as exc:
            logger.warning("advanced_news_fetch_failed", market_id=market.market_id, error=str(exc))
        context["llm_summary"] = await llm_processor.summarize_market(
            market_id=market.market_id,
            market_title=market.title,
            articles=articles,
            provider=llm_provider,
            as_of=as_of,
        )
        context["news_velocity"] = {
            "6h": float(
                sum(1 for article in articles if as_of - article.published_at <= timedelta(hours=6))
            ),
            "24h": float(
                sum(
                    1 for article in articles if as_of - article.published_at <= timedelta(hours=24)
                )
            ),
            "7d": float(len(articles)),
        }
    if use_onchain and onchain_processor is not None:
        context["onchain_snapshot"] = await onchain_processor.fetch_market_metrics(
            market, as_of=as_of
        )
    return context


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


def write_demo_signals(
    timestamps: list[datetime],
    *,
    output: Path,
    overwrite: bool,
    include_advanced: bool = False,
) -> None:
    for index, timestamp in enumerate(tqdm(timestamps, desc="demo-signals")):
        path = partition_path(output, timestamp)
        if path.exists() and not overwrite:
            continue
        rows = []
        for offset in range(3):
            row: dict[str, Any] = {
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
            if include_advanced:
                row.update(
                    {
                        "features": {
                            "llm_news_score": 0.08 + 0.02 * offset,
                            "llm_news_momentum": 0.03,
                            "llm_uncertainty": 0.35,
                            "llm_probability": 0.54 + 0.02 * offset,
                            "onchain_whale_activity": 0.1 * offset,
                            "onchain_funding_rate": 0.0,
                            "onchain_volume_surge": 0.05 * offset,
                            "onchain_open_interest_change": 0.0,
                            "onchain_tvl_change_24h": 0.02 * offset,
                            "cross_source_agreement": 0.67,
                            "cross_source_disagreement": 0.33,
                            "news_velocity_6h": 1.0 + offset,
                            "news_velocity_24h": 3.0 + offset,
                            "news_velocity_7d": 8.0 + offset,
                        },
                        "advanced_enabled": True,
                    }
                )
            rows.append(row)
        write_partition(pd.DataFrame(rows), path)


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
