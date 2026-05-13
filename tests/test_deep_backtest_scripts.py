from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pandas as pd

from scripts.deep_backtest import (
    DeepRunSpec,
    add_demo_advanced_columns,
    apply_relaxed_defaults,
    execute_run,
    filter_crypto_signals,
    prepare_signals_for_variant,
)
from scripts.generate_report import build_markdown_report, make_equity_chart


def test_prepare_signals_for_variant_uses_advanced_probability() -> None:
    frame = add_demo_advanced_columns(
        pd.DataFrame(
            {
                "market_id": ["m1"],
                "category": ["crypto"],
                "as_of": pd.to_datetime(["2025-01-01"], utc=True),
                "resolved_at": pd.to_datetime(["2025-01-08"], utc=True),
                "venue": ["polymarket"],
                "market_probability": [0.45],
                "model_probability": [0.50],
                "outcome": [1],
            }
        )
    )

    base = prepare_signals_for_variant(frame, use_advanced=False)
    advanced = prepare_signals_for_variant(frame, use_advanced=True)

    assert base["model_probability"].iloc[0] == frame["base_model_probability"].iloc[0]
    assert advanced["model_probability"].iloc[0] == frame["advanced_model_probability"].iloc[0]


def test_filter_crypto_signals_uses_category() -> None:
    frame = pd.DataFrame({"market_id": ["a", "b"], "category": ["crypto", "election"]})

    filtered = filter_crypto_signals(frame)

    assert filtered["market_id"].tolist() == ["a"]


def test_execute_run_and_report_generation(tmp_path: Path) -> None:
    signals = add_demo_advanced_columns(
        pd.DataFrame(
            {
                "market_id": [f"m{index}" for index in range(6)],
                "category": ["crypto", "politics"] * 3,
                "as_of": pd.date_range("2025-01-01", periods=6, freq="D", tz="UTC"),
                "resolved_at": pd.date_range("2025-01-08", periods=6, freq="D", tz="UTC"),
                "venue": ["polymarket"] * 6,
                "market_probability": [0.45, 0.52, 0.48, 0.55, 0.44, 0.51],
                "model_probability": [0.55, 0.48, 0.56, 0.50, 0.53, 0.47],
                "outcome": [1, 0, 1, 0, 1, 0],
            }
        )
    )
    args = Namespace(
        strategy="gbdt_v1",
        edge_threshold=0.02,
        stake=100.0,
        polymarket_fee_bps=0.0,
        kalshi_fee_bps=7.0,
        slippage_bps=15.0,
        kelly_fraction=0.4,
        max_exposure=0.25,
        min_post_cost_edge=0.05,
        liquidity_cap_multiplier=1.0,
        ignore_liquidity_cap=False,
        relaxed=False,
        quarter_kelly=False,
        diagnostic_mode=False,
        mode="hybrid",
        no_save_db=True,
    )

    artifact = execute_run(
        DeepRunSpec(name="advanced", use_advanced_features=True, portfolio=True),
        signals=signals,
        args=args,
        period_start=None,
        period_end=None,
        run_dir=tmp_path,
    )

    assert artifact.name == "advanced"
    assert (tmp_path / "runs" / "advanced" / "metrics.json").exists()

    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir()
    (tmp_path / "manifest.json").write_text(
        '{"created_at": "test", "args": {"relaxed": true}, "relaxed_warning": "RELAXED MODE - PnL not representative of strict risk rules"}'
    )
    (analysis_dir / "summary.json").write_text(
        '{"advanced": {"rubric_grade": "Fail", "go_no_go": "No-Go", "bet_count": 1, "net_pnl": 1, "brier_score": 0.2, "sharpe": 0}}'
    )
    pd.DataFrame(
        {"run": ["advanced"], "metric": ["net_pnl"], "value": [1.0], "delta": [1.0]}
    ).to_csv(analysis_dir / "ablation.csv", index=False)
    pd.DataFrame({"run": ["advanced"], "category": ["crypto"], "net_pnl": [1.0]}).to_csv(
        analysis_dir / "by_category.csv", index=False
    )
    pd.DataFrame({"run": ["advanced"], "total_turnover": [1.0]}).to_csv(
        analysis_dir / "capacity.csv", index=False
    )
    pd.DataFrame({"run": ["advanced"], "category": ["crypto"], "pnl": [-1.0]}).to_csv(
        analysis_dir / "failures.csv", index=False
    )
    make_equity_chart(tmp_path, analysis_dir / "equity_curves.svg")
    report = build_markdown_report(tmp_path, chart_path=analysis_dir / "equity_curves.svg")

    assert "Deep Backtest Report" in report
    assert "advanced" in report
    assert "RELAXED MODE - PnL not representative of strict risk rules" in report


def test_apply_relaxed_defaults_changes_strict_risk_defaults() -> None:
    args = Namespace(
        relaxed=True,
        edge_threshold=0.02,
        max_exposure=0.25,
        kelly_fraction=0.4,
        min_post_cost_edge=0.05,
        liquidity_cap_multiplier=1.0,
    )

    apply_relaxed_defaults(args)

    assert args.edge_threshold == 0.015
    assert args.max_exposure == 0.30
    assert args.kelly_fraction == 0.40
    assert args.min_post_cost_edge == 0.015
    assert args.liquidity_cap_multiplier == 2.0
