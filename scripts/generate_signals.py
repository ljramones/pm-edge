"""Generate reusable historical edge signal datasets."""

from __future__ import annotations

import argparse
import asyncio
import shutil
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
    parser = argparse.ArgumentParser(description="Generate a flat historical edge signal parquet.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--interval-hours", type=int, default=6)
    parser.add_argument("--markets", choices=["all", "high-volume"], default="high-volume")
    parser.add_argument("--min-volume", type=float, default=500_000)
    parser.add_argument("--venue", choices=[venue.value for venue in Venue], action="append")
    parser.add_argument("--output", type=Path, default=Path("data/processed/signals.parquet"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--include-outcomes",
        action="store_true",
        help="Join generated signals with resolved market outcomes for backtesting.",
    )
    parser.add_argument(
        "--resolved-markets",
        type=Path,
        default=Path("data/processed/resolved_markets.parquet"),
        help="Resolved-market parquet used by --include-outcomes.",
    )
    parser.add_argument(
        "--demo", action="store_true", help="Generate deterministic demo signals without APIs."
    )
    parser.add_argument("--use-llm", action="store_true", help="Enable cached LLM news features.")
    parser.add_argument(
        "--use-onchain", action="store_true", help="Enable crypto on-chain feature snapshots."
    )
    parser.add_argument(
        "--use-advanced-features",
        action="store_true",
        help="Compatibility flag: enable advanced feature columns in generated signals.",
    )
    parser.add_argument(
        "--fear-layer-enabled",
        action="store_true",
        help="Compatibility flag: include fear sizing defaults for downstream backtests.",
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

    output = coerce_single_file_output(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    prepare_single_file_output(output, overwrite=args.overwrite)
    if output.exists() and not args.overwrite:
        logger.info("signal_generation_output_exists", output=str(output))
        return 0
    timestamps = list(iter_timestamps(args.start_date, args.end_date, args.interval_hours))
    if args.demo:
        write_demo_signals(
            timestamps,
            output=output,
            overwrite=args.overwrite,
            include_advanced=advanced_features_enabled(args, settings),
        )
        return 0
    resolved_markets = (
        load_resolved_markets(args.resolved_markets) if args.include_outcomes else pd.DataFrame()
    )
    use_advanced = advanced_features_enabled(args, settings)
    if args.include_outcomes and not resolved_markets.empty:
        write_resolved_market_signals(
            timestamps,
            resolved_markets=resolved_markets,
            output=output,
            overwrite=args.overwrite,
            single_file=True,
            crypto_only=args.crypto_only,
            high_volume_only=args.markets == "high-volume",
            min_volume=args.min_volume,
            include_advanced=use_advanced,
        )
        return 0

    venues = [Venue(value) for value in args.venue] if args.venue else None
    llm_provider = cast(LLMProvider, args.llm_provider or settings.llm_provider)
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
        all_frames: list[pd.DataFrame] = []
        try:
            for timestamp in tqdm(timestamps, desc="signals"):
                if output.exists() and not args.overwrite:
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
                        build_signal_row(
                            market=market,
                            signal=signal,
                            timestamp=timestamp,
                            use_advanced=use_advanced,
                        )
                    )
                frame = pd.DataFrame(rows)
                if args.include_outcomes:
                    frame = attach_resolved_outcomes(frame, resolved_markets)
                all_frames.append(ensure_signal_schema(frame))
            combined = (
                pd.concat(all_frames, ignore_index=True)
                if all_frames
                else pd.DataFrame(columns=SIGNAL_COLUMNS)
            )
            if combined.empty:
                raise RuntimeError(
                    "Signal generation produced zero rows. Check market filters, venue backends, "
                    "and resolved market data. Refusing to write an empty backtest input."
                )
            write_partition(combined, output)
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


def is_single_file_output(path: Path) -> bool:
    """Return whether output should be written as one parquet file."""

    return path.suffix.lower() == ".parquet"


def coerce_single_file_output(path: Path) -> Path:
    """Return a single parquet output path for signal generation."""

    if path.suffix.lower() == ".parquet":
        return path
    return path.with_suffix(".parquet")


def advanced_features_enabled(args: argparse.Namespace, settings: Any) -> bool:
    """Return whether generated signals should include advanced feature columns."""

    return bool(
        args.use_llm
        or args.use_onchain
        or args.use_advanced_features
        or getattr(settings, "use_advanced_features", False)
    )


def prepare_single_file_output(path: Path, *, overwrite: bool) -> None:
    """Validate or clean a single-file output path before writing."""

    if path.is_dir():
        if not overwrite:
            raise IsADirectoryError(
                f"Output path {path} is an existing directory. Pass --overwrite to replace it "
                "with a single parquet file, or choose a directory output path."
            )
        shutil.rmtree(path)
    elif path.exists() and overwrite:
        path.unlink()


def write_partition(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        raise IsADirectoryError(
            f"Cannot write parquet file because output path is a directory: {path}"
        )
    frame = ensure_signal_schema(frame)
    frame.to_parquet(path, index=False)


SIGNAL_COLUMNS = [
    "market_id",
    "question",
    "condition_id",
    "slug",
    "outcome",
    "resolved_at",
    "as_of",
    "venue",
    "market_probability",
    "model_probability",
    "edge",
    "confidence",
    "features",
    "reasoning",
    "category",
    "liquidity",
    "volume",
    "fear_sizing_multiplier",
    "advanced_enabled",
]


def build_signal_row(
    *,
    market: UnifiedMarket,
    signal: Any,
    timestamp: datetime,
    use_advanced: bool,
) -> dict[str, Any]:
    """Build one complete signal row with backtest schema columns."""

    raw = market.raw
    return {
        "market_id": signal.market_id,
        "question": market.title,
        "condition_id": raw.get("conditionId") or raw.get("condition_id"),
        "slug": raw.get("slug"),
        "outcome": infer_market_outcome(raw),
        "resolved_at": infer_resolved_at(market),
        "as_of": timestamp,
        "venue": market.venue.value,
        "market_probability": signal.market_prob,
        "model_probability": signal.model_prob,
        "edge": signal.edge,
        "confidence": signal.confidence,
        "features": signal.features,
        "reasoning": signal.reasoning,
        "category": raw.get("category"),
        "liquidity": raw.get("liquidity"),
        "volume": raw.get("volume"),
        "fear_sizing_multiplier": 1.0,
        "advanced_enabled": use_advanced,
    }


def ensure_signal_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """Ensure every signal partition has the full expected signal schema."""

    output = frame.copy()
    for column in SIGNAL_COLUMNS:
        if column not in output:
            output[column] = pd.NA
    output["fear_sizing_multiplier"] = output["fear_sizing_multiplier"].fillna(1.0)
    if (
        "edge" in output
        and output["edge"].isna().all()
        and {
            "model_probability",
            "market_probability",
        }.issubset(output.columns)
    ):
        output["edge"] = output["model_probability"].astype(float) - output[
            "market_probability"
        ].astype(float)
    return output[
        SIGNAL_COLUMNS + [column for column in output.columns if column not in SIGNAL_COLUMNS]
    ]


def load_resolved_markets(path: Path) -> pd.DataFrame:
    """Load resolved market parquet for outcome joins."""

    if not path.exists():
        raise FileNotFoundError(
            f"Resolved market file not found: {path}. "
            "Run scripts.backfill_polymarket first or pass --resolved-markets."
        )
    frame = pd.read_parquet(path)
    if frame.empty:
        raise ValueError(f"Resolved market file is empty: {path}")
    return frame


def attach_resolved_outcomes(signals: pd.DataFrame, resolved_markets: pd.DataFrame) -> pd.DataFrame:
    """Fill outcome/resolved_at by matching signals to resolved market rows."""

    if signals.empty:
        return ensure_signal_schema(signals)
    output = ensure_signal_schema(signals)
    resolved_lookup = build_resolved_lookup(resolved_markets)
    outcomes: list[Any] = []
    resolved_times: list[Any] = []
    for row in output.to_dict(orient="records"):
        match = find_resolved_match(row, resolved_lookup)
        existing_outcome = row.get("outcome")
        existing_resolved_at = row.get("resolved_at")
        outcomes.append(
            normalize_outcome_value(existing_outcome)
            if not pd.isna(existing_outcome)
            else (match["outcome"] if match else pd.NA)
        )
        resolved_times.append(
            existing_resolved_at
            if not pd.isna(existing_resolved_at)
            else (match["resolved_at"] if match else pd.NaT)
        )
    output["outcome"] = outcomes
    output["resolved_at"] = pd.to_datetime(resolved_times, utc=True, errors="coerce")
    return output


def build_resolved_lookup(resolved_markets: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Build a lookup over common resolved-market identifiers."""

    lookup: dict[str, dict[str, Any]] = {}
    for row in resolved_markets.to_dict(orient="records"):
        outcome = resolved_row_outcome(row)
        resolved_at = row.get("resolved_at") or row.get("closed_time") or row.get("end_date")
        match = {"outcome": outcome, "resolved_at": resolved_at}
        for column in ["market_id", "condition_id", "slug"]:
            value = row.get(column)
            if value is not None and not pd.isna(value):
                lookup[f"{column}:{value}"] = match
    return lookup


def find_resolved_match(
    row: dict[str, Any], lookup: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Find resolved-market match by market id, condition id, or slug."""

    for column in ["market_id", "condition_id", "slug"]:
        value = row.get(column)
        if value is None or pd.isna(value):
            continue
        match = lookup.get(f"{column}:{value}")
        if match is not None:
            return match
    return None


def resolved_row_outcome(row: dict[str, Any]) -> Any:
    """Infer binary outcome from one resolved market parquet row."""

    if row.get("outcome") is not None and not pd.isna(row.get("outcome")):
        return normalize_outcome_value(row.get("outcome"))
    winning = row.get("winning_outcome")
    if winning is not None and not pd.isna(winning):
        return normalize_outcome_value(winning)
    yes_price = row.get("yes_price")
    no_price = row.get("no_price")
    if (
        yes_price is not None
        and no_price is not None
        and not pd.isna(yes_price)
        and not pd.isna(no_price)
    ):
        return int(float(yes_price) >= float(no_price))
    return pd.NA


def normalize_outcome_value(value: Any) -> Any:
    """Normalize outcome encodings to binary 1/0."""

    if value is None or pd.isna(value):
        return pd.NA
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"yes", "true", "1", "win", "winner"}:
            return 1
        if normalized in {"no", "false", "0", "lose", "loser"}:
            return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return pd.NA


def infer_market_outcome(raw: dict[str, Any]) -> Any:
    """Infer outcome from raw market payload when already available."""

    for key in ["outcome", "resolvedOutcome", "winning_outcome", "winningOutcome"]:
        value = raw.get(key)
        normalized = normalize_outcome_value(value)
        if not pd.isna(normalized):
            return normalized
    return pd.NA


def infer_resolved_at(market: UnifiedMarket) -> Any:
    """Infer market resolution timestamp from normalized or raw fields."""

    raw = market.raw
    for key in ["resolved_at", "resolvedAt", "closedTime", "endDate", "endDateIso"]:
        value = raw.get(key)
        if value:
            return value
    return market.closes_at if market.closes_at else pd.NaT


def write_resolved_market_signals(
    timestamps: list[datetime],
    *,
    resolved_markets: pd.DataFrame,
    output: Path,
    overwrite: bool,
    single_file: bool,
    crypto_only: bool,
    high_volume_only: bool,
    min_volume: float,
    include_advanced: bool,
) -> None:
    """Generate historical signal rows from resolved-market backfill data."""

    if single_file and output.exists() and not overwrite:
        return
    all_frames: list[pd.DataFrame] = []
    for timestamp in tqdm(timestamps, desc="resolved-signals"):
        path = output if single_file else partition_path(output, timestamp)
        if path.exists() and not overwrite:
            continue
        rows = [
            resolved_signal_row(row, timestamp=timestamp, include_advanced=include_advanced)
            for row in active_resolved_market_rows(
                resolved_markets,
                timestamp=timestamp,
                crypto_only=crypto_only,
                high_volume_only=high_volume_only,
                min_volume=min_volume,
            )
        ]
        frame = ensure_signal_schema(pd.DataFrame(rows))
        if single_file:
            all_frames.append(frame)
        else:
            write_partition(frame, path)
    if single_file:
        combined = (
            pd.concat(all_frames, ignore_index=True)
            if all_frames
            else pd.DataFrame(columns=SIGNAL_COLUMNS)
        )
        if combined.empty:
            raise RuntimeError(
                "Resolved-market signal generation produced zero rows. Check --start-date, "
                "--end-date, --crypto-only, --markets, and --min-volume."
            )
        write_partition(combined, output)


def active_resolved_market_rows(
    resolved_markets: pd.DataFrame,
    *,
    timestamp: datetime,
    crypto_only: bool,
    high_volume_only: bool,
    min_volume: float,
) -> list[dict[str, Any]]:
    """Return resolved markets that were open at the requested timestamp."""

    frame = resolved_markets.copy()
    if crypto_only:
        frame = frame[frame.apply(is_crypto_resolved_row, axis=1)]
    if high_volume_only:
        volume = pd.to_numeric(
            frame.get("volume_num", frame.get("volume", 0.0)), errors="coerce"
        ).fillna(0.0)
        frame = frame[volume >= min_volume]
    start = pd.to_datetime(
        frame.get("start_date", frame.get("created_at")), utc=True, errors="coerce"
    ).fillna(pd.to_datetime(frame.get("created_at"), utc=True, errors="coerce"))
    closed = pd.to_datetime(
        frame.get("closed_time", frame.get("end_date")), utc=True, errors="coerce"
    ).fillna(pd.to_datetime(frame.get("end_date"), utc=True, errors="coerce"))
    as_of = pd.Timestamp(timestamp)
    frame = frame[(start <= as_of) & (closed > as_of)]
    if not frame.empty:
        binary_mask = frame.apply(
            lambda row: not pd.isna(resolved_row_outcome(row.to_dict())),
            axis=1,
        )
        frame = frame[binary_mask]
    return cast(list[dict[str, Any]], frame.to_dict(orient="records"))


def resolved_signal_row(
    row: dict[str, Any], *, timestamp: datetime, include_advanced: bool
) -> dict[str, Any]:
    """Build one backtest signal from a resolved-market row."""

    market_probability = resolved_market_probability(row)
    model_probability = resolved_model_probability(row, market_probability, include_advanced)
    features = resolved_signal_features(row, model_probability=model_probability)
    output = {
        "market_id": str(row.get("market_id")),
        "question": row.get("question"),
        "condition_id": row.get("condition_id"),
        "slug": row.get("slug"),
        "outcome": resolved_row_outcome(row),
        "resolved_at": row.get("closed_time") or row.get("end_date"),
        "as_of": timestamp,
        "venue": Venue.POLYMARKET.value,
        "market_probability": market_probability,
        "model_probability": model_probability,
        "edge": model_probability - market_probability,
        "confidence": min(abs(model_probability - market_probability) / 0.10, 1.0),
        "features": features,
        "reasoning": ["resolved-market backfill bootstrap signal"],
        "category": row.get("category") or "crypto",
        "liquidity": numeric_value(row.get("liquidity_num"), row.get("liquidity"), default=0.0),
        "volume": numeric_value(row.get("volume_num"), row.get("volume"), default=0.0),
        "fear_sizing_multiplier": 1.0,
        "advanced_enabled": include_advanced,
        "price_source": "resolved_market_snapshot",
    }
    if include_advanced:
        output["base_model_probability"] = resolved_model_probability(
            row, market_probability, include_advanced=False
        )
        output["advanced_model_probability"] = model_probability
    return output


def resolved_market_probability(row: dict[str, Any]) -> float:
    """Return a bounded probability from resolved-market price fields."""

    value = numeric_value(row.get("last_trade_price"), row.get("yes_price"), default=0.5)
    return min(max(value, 0.001), 0.999)


def resolved_model_probability(
    row: dict[str, Any], market_probability: float, include_advanced: bool
) -> float:
    """Generate a deterministic bootstrap model probability for resolved-market rows."""

    title = str(row.get("question") or "").lower()
    liquidity = numeric_value(row.get("liquidity_num"), row.get("liquidity"), default=0.0)
    volume = numeric_value(row.get("volume_num"), row.get("volume"), default=0.0)
    liquidity_score = min(volume / max(liquidity, 1.0), 5.0) / 5.0 if liquidity else 0.0
    title_score = 0.0
    if any(token in title for token in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol"]):
        title_score += 0.03
    if any(token in title for token in ["above", "higher", "all-time high", "ath"]):
        title_score -= 0.02
    if any(token in title for token in ["below", "lower", "crash"]):
        title_score += 0.02
    advanced = 0.02 * liquidity_score if include_advanced else 0.0
    probability = 0.50 + title_score + advanced
    if market_probability > 0.90:
        probability = min(probability, 0.70)
    elif market_probability < 0.10:
        probability = max(probability, 0.30)
    return min(max(probability, 0.01), 0.99)


def resolved_signal_features(row: dict[str, Any], *, model_probability: float) -> dict[str, float]:
    """Build feature payload for resolved-market bootstrap rows."""

    liquidity = numeric_value(row.get("liquidity_num"), row.get("liquidity"), default=0.0)
    volume = numeric_value(row.get("volume_num"), row.get("volume"), default=0.0)
    spread = max(
        0.0,
        numeric_value(row.get("best_ask"), default=1.0)
        - numeric_value(row.get("best_bid"), default=0.0),
    )
    return {
        "top_book_liquidity": liquidity,
        "spread": spread,
        "mention_count_7d": 0.0,
        "llm_probability": model_probability,
        "llm_news_score": (model_probability - 0.5) * 2,
        "llm_news_momentum": 0.0,
        "llm_uncertainty": 0.5,
        "cross_source_agreement": 0.5,
        "onchain_whale_activity": min(volume / max(liquidity, 1.0), 5.0) if liquidity else 0.0,
        "onchain_funding_rate": 0.0,
        "onchain_volume_surge": min(volume / max(liquidity, 1.0), 5.0) if liquidity else 0.0,
        "onchain_tvl_change_24h": 0.0,
        "fear_sizing_multiplier": 1.0,
    }


def is_crypto_resolved_row(row: pd.Series) -> bool:
    """Return whether a resolved-market row is crypto-linked."""

    text = " ".join(
        [
            str(row.get("question") or ""),
            str(row.get("category") or ""),
            str(row.get("slug") or ""),
            str(row.get("event_slug") or ""),
            tags_text(row.get("tags")),
        ]
    ).lower()
    return any(
        token in text
        for token in ["crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "blockchain"]
    )


def tags_text(value: Any) -> str:
    """Render list/array/string tags into searchable text."""

    if value is None:
        return ""
    if isinstance(value, list | tuple | set):
        return " ".join(str(item) for item in value if item is not None)
    if hasattr(value, "tolist"):
        converted = value.tolist()
        if isinstance(converted, list):
            return " ".join(str(item) for item in converted if item is not None)
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def numeric_value(*values: Any, default: float) -> float:
    """Return first finite numeric value from candidates."""

    for value in values:
        if value is None or pd.isna(value):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def write_demo_signals(
    timestamps: list[datetime],
    *,
    output: Path,
    overwrite: bool,
    include_advanced: bool = False,
) -> None:
    single_file = is_single_file_output(output)
    if single_file:
        output.parent.mkdir(parents=True, exist_ok=True)
        prepare_single_file_output(output, overwrite=overwrite)
    if single_file and output.exists() and not overwrite:
        return
    all_rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(tqdm(timestamps, desc="demo-signals")):
        path = output if single_file else partition_path(output, timestamp)
        if path.exists() and not overwrite:
            continue
        rows = []
        for offset in range(3):
            row: dict[str, Any] = {
                "market_id": f"demo-{index}-{offset}",
                "question": f"Demo market {index}-{offset}",
                "condition_id": f"demo-condition-{index}-{offset}",
                "slug": f"demo-market-{index}-{offset}",
                "as_of": timestamp,
                "resolved_at": timestamp + timedelta(days=14),
                "venue": "polymarket" if offset % 2 else "kalshi",
                "market_probability": 0.42 + offset * 0.02,
                "model_probability": 0.47 + offset * 0.02,
                "edge": 0.05,
                "confidence": 0.6,
                "liquidity": 750_000,
                "volume": 1_000_000,
                "fear_sizing_multiplier": 1.0,
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
        if single_file:
            all_rows.extend(rows)
        else:
            write_partition(pd.DataFrame(rows), path)
    if single_file:
        write_partition(pd.DataFrame(all_rows), output)


def main() -> None:
    try:
        raise SystemExit(asyncio.run(run()))
    except (FileNotFoundError, IsADirectoryError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"generate_signals failed: {exc}") from None


if __name__ == "__main__":
    main()
