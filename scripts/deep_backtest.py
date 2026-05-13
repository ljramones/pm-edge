"""Run large-scale deep backtests and save structured diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting import (
    BacktestConfig,
    Backtester,
    DeepRunArtifact,
    FeeModel,
    PortfolioBacktester,
    analyze_deep_backtest,
)
from backtesting.deep_analysis import flatten_feature_column
from backtesting.portfolio_backtester import portfolio_config_from_backtest_config
from core import get_settings
from execution import MonteCarloRuinSimulator
from features import FearLayerRouter, FearSnapshot
from monitoring import TelegramNotifier
from scripts.backtest import demo_signals, parse_period
from strategies import backtest_liquidity
from utils import configure_logging, get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DeepRunSpec:
    """One deep-backtest variant."""

    name: str
    use_advanced_features: bool
    portfolio: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deep strategy backtests and analysis.")
    parser.add_argument("--period", help="Inclusive period in YYYY-MM-DD:YYYY-MM-DD format.")
    parser.add_argument("--strategy", default="gbdt_v1")
    parser.add_argument("--signals", type=Path, help="Signal parquet/csv file or partitioned dir.")
    parser.add_argument("--output", type=Path, default=Path("data/processed/deep_backtests"))
    parser.add_argument("--use-advanced-features", action="store_true")
    parser.add_argument("--crypto-only", action="store_true")
    parser.add_argument(
        "--mode", choices=["directional", "liquidity-harvest", "hybrid"], default="directional"
    )
    parser.add_argument("--fear-layer-enabled", action="store_true")
    parser.add_argument("--quarter-kelly", action="store_true")
    parser.add_argument("--min-post-cost-edge", type=float, default=0.05)
    parser.add_argument(
        "--diagnostic-mode",
        action="store_true",
        help="Ignore portfolio liquidity caps and save allocation rejection diagnostics.",
    )
    parser.add_argument("--portfolio", action="store_true")
    parser.add_argument("--compare", action="store_true", default=True)
    parser.add_argument("--edge-threshold", type=float, default=0.02)
    parser.add_argument("--stake", type=float, default=100.0)
    parser.add_argument("--kelly-fraction", type=float, default=0.4)
    parser.add_argument("--max-exposure", type=float, default=0.25)
    parser.add_argument("--slippage-bps", type=float, default=15.0)
    parser.add_argument("--kalshi-fee-bps", type=float, default=7.0)
    parser.add_argument("--polymarket-fee-bps", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--demo", action="store_true", help="Use deterministic demo signals.")
    parser.add_argument("--no-save-db", action="store_true")
    parser.add_argument("--notify", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    period_start, period_end = normalize_period(*parse_period(args.period))
    signals = load_signal_frame(args.signals, demo=args.demo or args.signals is None)
    signals = add_demo_advanced_columns(signals) if args.demo or args.signals is None else signals
    if args.crypto_only:
        signals = filter_crypto_signals(signals)
    if signals.empty:
        raise ValueError(
            "No signals remain after loading and filters. Check --signals, --crypto-only, "
            "and whether the parquet file has rows."
        )
    if args.fear_layer_enabled:
        signals = add_fear_layer_columns(signals)
    run_dir = make_run_dir(args.output, args.strategy)
    (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    signals.to_parquet(run_dir / "inputs" / "signals.parquet", index=False)

    specs = build_run_specs(args)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        artifacts = list(
            pool.map(
                lambda spec: execute_run(
                    spec,
                    signals=signals,
                    args=args,
                    period_start=period_start,
                    period_end=period_end,
                    run_dir=run_dir,
                ),
                specs,
            )
        )

    analysis = analyze_deep_backtest(artifacts)
    save_analysis(run_dir / "analysis", analysis)
    write_manifest(run_dir, args=args, artifacts=artifacts)
    print(f"Deep backtest saved to {run_dir}")
    for artifact in artifacts:
        print(
            f"{artifact.name:>12}: grade={artifact.rubric.get('grade')} "
            f"go_no_go={artifact.rubric.get('go_no_go')} "
            f"bets={artifact.metrics.get('bet_count', 0):.0f} "
            f"pnl={artifact.metrics.get('net_pnl', 0):.2f}"
        )
    if args.notify:
        asyncio.run(notify_deep_backtest(settings=settings, artifacts=artifacts, run_dir=run_dir))


async def notify_deep_backtest(
    *, settings: Any, artifacts: list[DeepRunArtifact], run_dir: Path
) -> None:
    """Send optional Telegram summary for a completed deep backtest."""

    notifier = TelegramNotifier(settings=settings)
    try:
        high_fear = top_high_fear_setup(artifacts)
        if high_fear is not None:
            await notifier.high_fear_setup(
                market_id=str(high_fear["market_id"]),
                fear_score=float(high_fear["fear_score"]),
                temperature=float(high_fear["market_temperature"]),
                edge=float(high_fear["edge"]),
                link=str(high_fear["url"]) if high_fear.get("url") else None,
            )
        await notifier.daily_summary(
            {
                "run_dir": str(run_dir),
                **{
                    f"{artifact.name}_grade": artifact.rubric.get("grade") for artifact in artifacts
                },
                **{
                    f"{artifact.name}_pnl": artifact.metrics.get("net_pnl", 0.0)
                    for artifact in artifacts
                },
            }
        )
    finally:
        await notifier.close()


def top_high_fear_setup(artifacts: list[DeepRunArtifact]) -> dict[str, Any] | None:
    """Return the highest-scored routed high-fear signal, if available."""

    frames = []
    for artifact in artifacts:
        frame = artifact.signals
        if {"fear_score", "market_temperature", "edge", "market_id"}.issubset(frame.columns):
            frames.append(frame.copy())
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    combined["fear_rank_score"] = (
        combined["fear_score"].astype(float)
        * combined["market_temperature"].astype(float)
        * combined["edge"].astype(float).abs()
    )
    if combined["fear_rank_score"].max() <= 0:
        return None
    return dict(combined.sort_values("fear_rank_score", ascending=False).iloc[0])


def execute_run(
    spec: DeepRunSpec,
    *,
    signals: pd.DataFrame,
    args: argparse.Namespace,
    period_start: datetime | None,
    period_end: datetime | None,
    run_dir: Path,
) -> DeepRunArtifact:
    """Execute one deep-backtest variant and persist its outputs."""

    run_signals = prepare_signals_for_variant(signals, use_advanced=spec.use_advanced_features)
    config = BacktestConfig(
        strategy_name=f"{args.strategy}_{spec.name}",
        edge_threshold=args.edge_threshold,
        stake=args.stake,
        fee_model=FeeModel(
            polymarket_fee_bps=args.polymarket_fee_bps,
            kalshi_fee_bps=args.kalshi_fee_bps,
            slippage_bps=args.slippage_bps,
        ),
        save_results=False,
    )
    output_dir = run_dir / "runs" / spec.name
    output_dir.mkdir(parents=True, exist_ok=True)
    run_signals.to_parquet(output_dir / "signals.parquet", index=False)
    if spec.portfolio:
        portfolio_config = portfolio_config_from_backtest_config(
            config,
            kelly_fraction=0.25 if getattr(args, "quarter_kelly", False) else args.kelly_fraction,
            max_exposure=args.max_exposure,
            quarter_kelly=getattr(args, "quarter_kelly", False),
            min_post_cost_edge=getattr(args, "min_post_cost_edge", 0.0),
            diagnostic_mode=getattr(args, "diagnostic_mode", False),
        )
        portfolio_result = PortfolioBacktester(portfolio_config).run(
            run_signals,
            period_start=period_start,
            period_end=period_end,
        )
        trades = portfolio_result.trades_frame()
        equity = portfolio_result.equity_frame()
        trades.to_parquet(output_dir / "trades.parquet", index=False)
        equity.to_parquet(output_dir / "equity_curve.parquet", index=False)
        save_json(output_dir / "metrics.json", portfolio_result.report.metrics)
        save_json(output_dir / "rubric.json", portfolio_result.rubric.model_dump(mode="json"))
        save_json(
            output_dir / "calibration.json",
            [bucket.model_dump(mode="json") for bucket in portfolio_result.report.calibration],
        )
        save_json(output_dir / "portfolio_diagnostics.json", portfolio_result.diagnostics)
        metrics = dict(portfolio_result.report.metrics)
        metrics.update(
            {
                f"diagnostic_{key}": value
                for key, value in portfolio_result.diagnostics.items()
                if isinstance(value, int | float | bool)
            }
        )
        trades_for_artifact = trades
        if getattr(args, "mode", "directional") in {"liquidity-harvest", "hybrid"}:
            liquidity = backtest_liquidity(run_signals)
            liquidity.to_parquet(output_dir / "liquidity_trades.parquet", index=False)
            liquidity_pnl = float(liquidity["pnl"].sum()) if not liquidity.empty else 0.0
            metrics["liquidity_pnl"] = liquidity_pnl
            metrics["hybrid_net_pnl"] = metrics.get("net_pnl", 0.0) + liquidity_pnl
            metrics["liquidity_quote_count"] = (
                float(liquidity["should_quote"].sum()) if not liquidity.empty else 0.0
            )
        mc = MonteCarloRuinSimulator(starting_capital=portfolio_config.starting_capital).run(
            trades_for_artifact["pnl"] if not trades_for_artifact.empty else pd.Series(dtype=float)
        )
        save_json(output_dir / "monte_carlo_ruin.json", mc.model_dump(mode="json"))
        metrics["monte_carlo_ruin_probability"] = mc.ruin_probability
        save_json(output_dir / "metrics.json", metrics)
        return DeepRunArtifact(
            name=spec.name,
            metrics=metrics,
            rubric=portfolio_result.rubric.model_dump(mode="json"),
            signals=run_signals,
            bets=trades_for_artifact,
            equity_curve=equity,
        )

    backtest_result = Backtester(config=config).run(
        run_signals,
        period_start=period_start,
        period_end=period_end,
    )
    bets = backtest_result.bets_frame()
    bets.to_parquet(output_dir / "bets.parquet", index=False)
    save_json(output_dir / "metrics.json", backtest_result.report.metrics)
    save_json(output_dir / "rubric.json", backtest_result.rubric.model_dump(mode="json"))
    save_json(
        output_dir / "calibration.json",
        [bucket.model_dump(mode="json") for bucket in backtest_result.report.calibration],
    )
    return DeepRunArtifact(
        name=spec.name,
        metrics=backtest_result.report.metrics,
        rubric=backtest_result.rubric.model_dump(mode="json"),
        signals=run_signals,
        bets=bets,
    )


def build_run_specs(args: argparse.Namespace) -> list[DeepRunSpec]:
    """Return run variants for requested comparison."""

    specs = [DeepRunSpec(name="base", use_advanced_features=False, portfolio=args.portfolio)]
    if args.use_advanced_features:
        specs.append(
            DeepRunSpec(name="advanced", use_advanced_features=True, portfolio=args.portfolio)
        )
    return specs


def load_signal_frame(path: Path | None, *, demo: bool) -> pd.DataFrame:
    """Load signal rows from file, directory, or deterministic demo fixture."""

    if demo:
        return demo_signals()
    if path is None:
        raise ValueError("--signals is required unless --demo is set")
    if path.is_dir():
        files = sorted(path.glob("date=*/signals.parquet"))
        if not files:
            files = sorted(path.glob("*.parquet"))
        if not files:
            raise ValueError(f"No parquet signal files found in {path}")
        return pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def filter_crypto_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Return only crypto-linked historical signals."""

    if "category" in frame:
        return frame[frame["category"].astype(str).str.lower().str.contains("crypto")].copy()
    text = frame.get("market_id", pd.Series("", index=frame.index)).astype(str).str.lower()
    mask = text.str.contains("btc|bitcoin|eth|ethereum|sol|crypto")
    return frame[mask].copy()


def prepare_signals_for_variant(frame: pd.DataFrame, *, use_advanced: bool) -> pd.DataFrame:
    """Select model probability columns for a base or advanced run."""

    output = flatten_feature_column(frame).copy()
    if use_advanced and "advanced_model_probability" in output:
        output["model_probability"] = output["advanced_model_probability"]
    elif not use_advanced and "base_model_probability" in output:
        output["model_probability"] = output["base_model_probability"]
    elif use_advanced and "llm_probability" in output:
        adjustment = (
            0.08 * (output["llm_probability"].astype(float).fillna(0.5) - 0.5)
            + 0.04 * optional_numeric(output, "llm_news_score")
            + 0.03 * optional_numeric(output, "onchain_tvl_change_24h")
        )
        output["model_probability"] = (output["model_probability"].astype(float) + adjustment).clip(
            0.001, 0.999
        )
    return output


def add_demo_advanced_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Add deterministic advanced-feature comparison columns to demo signals."""

    output = frame.copy()
    base = output["model_probability"].astype(float)
    signal_quality = np_where(output.index.to_series() % 4 == 0, -0.015, 0.018)
    output["base_model_probability"] = base
    output["advanced_model_probability"] = (base + signal_quality).clip(0.001, 0.999)
    output["confidence"] = (
        (output["advanced_model_probability"] - output["market_probability"]).abs().clip(0, 1)
    )
    output["liquidity"] = 750_000 + (output.index.to_series() % 5) * 100_000
    output["llm_probability"] = output["advanced_model_probability"]
    output["llm_news_score"] = (output["advanced_model_probability"] - 0.5) * 2
    output["onchain_tvl_change_24h"] = np_where(output["category"].eq("crypto"), 0.03, 0.0)
    output["funding_rate_momentum"] = np_where(output["category"].eq("crypto"), 0.012, 0.0)
    output["whale_flow_score"] = np_where(output["category"].eq("crypto"), 0.08, 0.0)
    output["panic_reversion_score"] = np_where(output.index.to_series() % 6 == 0, 0.05, 0.0)
    output["llm_reasoning"] = output["category"].map(
        {
            "crypto": "Demo crypto signal: synthetic on-chain momentum and news tone.",
            "election": "Demo politics signal: synthetic polling/news improvement.",
        }
    )
    output["spread"] = 0.025 + (output.index.to_series() % 4) * 0.01
    output["event_cluster"] = output["category"].astype(str)
    output["volume"] = output["liquidity"] * (0.5 + (output.index.to_series() % 3) * 0.2)
    return output


def add_fear_layer_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Add fear-layer routing and temperature columns."""

    output = frame.copy()
    router = FearLayerRouter()
    fear = FearSnapshot(vix=28, cnn_fear_greed=35, crypto_fear_greed=30)
    rows = [router.features(row, fear=fear) for row in output.to_dict(orient="records")]
    fear_frame = pd.DataFrame(rows)
    output = output.drop(columns=[column for column in fear_frame.columns if column in output])
    output = pd.concat([output.reset_index(drop=True), fear_frame.reset_index(drop=True)], axis=1)
    if "model_probability" in output:
        multiplier = output["fear_sizing_multiplier"].astype(float).clip(0.25, 1.25)
        edge = output["model_probability"].astype(float) - output["market_probability"].astype(
            float
        )
        output["model_probability"] = (
            output["market_probability"].astype(float) + edge * multiplier
        ).clip(0.001, 0.999)
    return output


def optional_numeric(frame: pd.DataFrame, column: str, *, default: float = 0.0) -> pd.Series:
    """Return a numeric column or a default-valued series."""

    if column not in frame:
        return pd.Series(default, index=frame.index)
    return frame[column].astype(float).fillna(default)


def save_analysis(path: Path, analysis: Any) -> None:
    """Persist deep-analysis tables."""

    path.mkdir(parents=True, exist_ok=True)
    save_json(path / "summary.json", analysis.summary)
    for name in [
        "ablation",
        "calibration",
        "edge_decay",
        "by_category",
        "regimes",
        "confidence_accuracy",
        "capacity",
        "failures",
        "feature_diagnostics",
        "feature_stability",
        "rubric_failures",
        "recommendations",
        "bootstrap_intervals",
    ]:
        frame = getattr(analysis, name)
        if not frame.empty:
            frame.to_csv(path / f"{name}.csv", index=False)
            frame.to_parquet(path / f"{name}.parquet", index=False)


def normalize_period(
    period_start: datetime | None, period_end: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Normalize optional CLI period bounds to UTC-aware datetimes."""

    return _ensure_utc(period_start), _ensure_utc(period_end)


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def write_manifest(
    run_dir: Path,
    *,
    args: argparse.Namespace,
    artifacts: list[DeepRunArtifact],
) -> None:
    """Write top-level run metadata."""

    save_json(
        run_dir / "manifest.json",
        {
            "created_at": datetime.now(tz=UTC).isoformat(),
            "args": vars(args),
            "runs": [
                {
                    "name": artifact.name,
                    "metrics": artifact.metrics,
                    "rubric": artifact.rubric,
                }
                for artifact in artifacts
            ],
        },
    )


def make_run_dir(root: Path, strategy: str) -> Path:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / f"{timestamp}_{strategy}"


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True))


def json_safe(value: Any) -> Any:
    """Convert common scientific/Pandas objects to JSON-safe values."""

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, float):
        if value == float("inf"):
            return "inf"
        if value == float("-inf"):
            return "-inf"
        if pd.isna(value):
            return None
        return value
    return value


def np_where(condition: Any, true_value: float, false_value: float) -> pd.Series:
    """Return a Series wrapper around numpy-style where."""

    return pd.Series(
        [true_value if bool(item) else false_value for item in condition],
        index=condition.index,
    )


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, IsADirectoryError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"deep_backtest failed: {exc}") from None
