"""Generate Markdown or HTML reports from deep-backtest outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import pandas as pd

from utils import resolve_repo_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a deep-backtest report.")
    parser.add_argument("--input", type=Path, default=Path("data/processed/deep_backtests"))
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.input = resolve_repo_path(args.input)
    if args.output is not None:
        args.output = resolve_repo_path(args.output)
    run_dir = resolve_run_dir(args.input)
    output = args.output or (run_dir / "report.md")
    chart_path = run_dir / "analysis" / "equity_curves.svg"
    make_equity_chart(run_dir, chart_path)
    markdown = build_markdown_report(run_dir, chart_path=chart_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".html":
        output.write_text(markdown_to_html(markdown))
    else:
        output.write_text(markdown)
    print(f"Report written to {output}")


def resolve_run_dir(path: Path) -> Path:
    """Return an explicit run dir or latest child run dir."""

    if (path / "manifest.json").exists():
        return path
    candidates = sorted([item for item in path.iterdir() if (item / "manifest.json").exists()])
    if not candidates:
        raise ValueError(f"No deep-backtest run directories found under {path}")
    return candidates[-1]


def build_markdown_report(run_dir: Path, *, chart_path: Path) -> str:
    """Build report markdown from saved deep-backtest artifacts."""

    manifest = read_json(run_dir / "manifest.json")
    summary = read_json(run_dir / "analysis" / "summary.json")
    ablation = read_table(run_dir / "analysis" / "ablation.csv")
    by_category = read_table(run_dir / "analysis" / "by_category.csv")
    capacity = read_table(run_dir / "analysis" / "capacity.csv")
    failures = read_table(run_dir / "analysis" / "failures.csv")
    feature_diagnostics = read_table(run_dir / "analysis" / "feature_diagnostics.csv")
    feature_stability = read_table(run_dir / "analysis" / "feature_stability.csv")
    rubric_failures = read_table(run_dir / "analysis" / "rubric_failures.csv")
    recommendation_rows = read_table(run_dir / "analysis" / "recommendations.csv")
    bootstrap = read_table(run_dir / "analysis" / "bootstrap_intervals.csv")

    lines = [
        "# pm-edge Deep Backtest Report",
        "",
        f"Run directory: `{run_dir}`",
        f"Created at: `{manifest.get('created_at', 'unknown')}`",
        "",
    ]
    if manifest.get("args", {}).get("relaxed"):
        lines.extend(
            [
                f"> **{manifest.get('relaxed_warning', 'RELAXED MODE - PnL not representative of strict risk rules')}**",
                "",
            ]
        )
    lines.extend(
        [
            "## Executive Summary",
            "",
            markdown_table(summary_rows(summary)),
            "",
            "## Equity Curves",
            "",
        ]
    )
    if chart_path.exists():
        lines.append(f"![Equity curves]({chart_path.relative_to(run_dir)})")
    else:
        lines.append("No portfolio equity curves were available for this run.")
    lines.extend(
        [
            "",
            "## Feature Ablation",
            "",
            markdown_table(frame_preview(ablation, ["run", "metric", "value", "delta"])),
            "",
            "## Category Performance",
            "",
            markdown_table(frame_preview(by_category)),
            "",
            "## Why We Failed The Rubric",
            "",
            markdown_table(
                frame_preview(
                    rubric_failures,
                    [
                        "run",
                        "primary_failure_mode",
                        "bet_count",
                        "brier_score",
                        "net_pnl",
                        "rubric_recommendation",
                    ],
                )
            ),
            "",
            "## Feature Diagnostics",
            "",
            markdown_table(
                frame_preview(
                    feature_diagnostics,
                    [
                        "run",
                        "feature",
                        "feature_outcome_corr",
                        "top_minus_bottom_hit_rate",
                        "noise_flag",
                    ],
                    limit=15,
                )
            ),
            "",
            "## Feature Stability",
            "",
            markdown_table(
                frame_preview(
                    (
                        feature_stability[feature_stability.get("quarter", "") == "all"]
                        if not feature_stability.empty
                        else feature_stability
                    ),
                    [
                        "run",
                        "feature",
                        "quarter_corr",
                        "stability_score",
                        "sign_flip_rate",
                    ],
                    limit=15,
                )
            ),
            "",
            "## Capacity And Slippage",
            "",
            markdown_table(frame_preview(capacity)),
            "",
            "## Failure Case Studies",
            "",
            markdown_table(frame_preview(failures, limit=10)),
            "",
            "## Recommendations",
            "",
            markdown_table(frame_preview(recommendation_rows)),
            "",
            "## Retail Capital Projection",
            "",
            markdown_table(capital_projection_rows(summary)),
            "",
            "## Bootstrap Confidence Intervals",
            "",
            markdown_table(frame_preview(bootstrap)),
            "",
            "## Report Notes",
            "",
        ]
    )
    lines.extend(recommendations(summary, ablation, failures, recommendation_rows))
    lines.append("")
    return "\n".join(lines)


def make_equity_chart(run_dir: Path, output: Path) -> None:
    """Create a lightweight SVG equity-curve comparison chart."""

    frames = []
    for run_path in sorted((run_dir / "runs").glob("*")):
        equity_path = run_path / "equity_curve.parquet"
        if not equity_path.exists():
            continue
        frame = pd.read_parquet(equity_path)
        if frame.empty:
            continue
        frame["run"] = run_path.name
        frames.append(frame)
    if not frames:
        return
    data = pd.concat(frames, ignore_index=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(equity_svg(data))


def equity_svg(data: pd.DataFrame) -> str:
    """Render simple SVG lines for portfolio equity curves without plotting deps."""

    width, height = 900, 420
    left, right, top, bottom = 60, 20, 20, 50
    plot_width = width - left - right
    plot_height = height - top - bottom
    data = data.copy()
    data["as_of"] = pd.to_datetime(data["as_of"], utc=True)
    x_values = data["as_of"].astype("int64")
    y_values = data["equity"].astype(float)
    min_x, max_x = int(x_values.min()), int(x_values.max())
    min_y, max_y = float(y_values.min()), float(y_values.max())
    if min_y == max_y:
        min_y -= 1
        max_y += 1

    def x_coord(value: int) -> float:
        if max_x == min_x:
            return left + plot_width / 2
        return left + (value - min_x) / (max_x - min_x) * plot_width

    def y_coord(value: float) -> float:
        return top + (max_y - value) / (max_y - min_y) * plot_height

    colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e"]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#444"/>',
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#444"/>',
        f'<text x="{left}" y="16" font-size="13" fill="#222">Portfolio Equity Curve</text>',
        f'<text x="8" y="{top + 12}" font-size="11" fill="#555">{max_y:.0f}</text>',
        f'<text x="8" y="{height - bottom}" font-size="11" fill="#555">{min_y:.0f}</text>',
    ]
    for run_name, group in data.groupby("run"):
        color = colors[len(lines) % len(colors)]
        points = " ".join(
            f"{x_coord(int(row['as_of'].value)):.1f},{y_coord(float(row['equity'])):.1f}"
            for _index, row in group.sort_values("as_of").iterrows()
        )
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{points}"/>')
        legend_y = top + 20 + 18 * list(data["run"].drop_duplicates()).index(run_name)
        lines.append(
            f'<text x="{width - 170}" y="{legend_y}" font-size="12" fill="{color}">{run_name}</text>'
        )
    lines.append("</svg>")
    return "\n".join(lines)


def recommendations(
    summary: dict[str, Any],
    ablation: pd.DataFrame,
    failures: pd.DataFrame,
    recommendation_rows: pd.DataFrame | None = None,
) -> list[str]:
    """Generate deterministic recommendation bullets from the analysis."""

    bullets: list[str] = []
    advanced = summary.get("advanced")
    base = summary.get("base")
    if isinstance(advanced, dict) and isinstance(base, dict):
        if float(advanced.get("net_pnl", 0.0)) > float(base.get("net_pnl", 0.0)):
            bullets.append(
                "- Advanced features improved net PnL in this run; prioritize cost-controlled LLM/on-chain scoring in the strongest categories."
            )
        else:
            bullets.append(
                "- Advanced features did not improve net PnL; keep them behind flags until ablation is positive on a larger holdout."
            )
    if not failures.empty and "category" in failures:
        worst = failures["category"].value_counts().index[0]
        bullets.append(
            f"- Largest losses cluster first in `{worst}`; review category-specific thresholds."
        )
    if ablation.empty:
        bullets.append("- Run with `--use-advanced-features` to populate before/after ablation.")
    if recommendation_rows is not None and not recommendation_rows.empty:
        top_recommendation = str(recommendation_rows.iloc[-1].get("recommendation", ""))
        bullets.append(f"- Phase 6 recommendation: {top_recommendation}.")
    bullets.append(
        "- Treat any Go result as paper-trading approval only until live slippage and operational checks are validated."
    )
    return bullets


def markdown_table(rows: list[dict[str, Any]]) -> str:
    """Render a compact markdown table."""

    if not rows:
        return "_No data._"
    columns = list(rows[0])
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(format_value(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def summary_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "run": run,
            "grade": values.get("rubric_grade"),
            "go_no_go": values.get("go_no_go"),
            "bets": values.get("bet_count"),
            "net_pnl": values.get("net_pnl"),
            "hybrid_pnl": values.get("hybrid_net_pnl"),
            "ruin_prob": values.get("monte_carlo_ruin_probability"),
            "brier": values.get("brier_score"),
            "sharpe": values.get("sharpe"),
        }
        for run, values in summary.items()
        if isinstance(values, dict)
    ]


def capital_projection_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Return simple retail-capital projections from the observed hybrid return."""

    rows = []
    for run, values in summary.items():
        if not isinstance(values, dict):
            continue
        hybrid_pnl = float(values.get("hybrid_net_pnl") or values.get("net_pnl") or 0.0)
        observed_return = hybrid_pnl / 10_000
        go_no_go = str(values.get("go_no_go", "No-Go"))
        rows.append(
            {
                "run": run,
                "verdict": go_no_go,
                "paper_25k_projection": 25_000 * (1 + observed_return),
                "paper_50k_projection": 50_000 * (1 + observed_return),
                "real_money_guidance": (
                    "$50k-$150k only after fresh Decision-Grade holdout"
                    if go_no_go.lower() == "go"
                    else "No real-money scale; continue paper/backfill only"
                ),
            }
        )
    return rows


def frame_preview(
    frame: pd.DataFrame,
    columns: list[str] | None = None,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    available_columns = [column for column in (columns or list(frame.columns)) if column in frame]
    selected = frame[available_columns] if available_columns else frame
    return cast(list[dict[str, Any]], selected.head(limit).to_dict(orient="records"))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    return payload if isinstance(payload, dict) else {}


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def markdown_to_html(markdown: str) -> str:
    escaped = markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<html><body><pre>{escaped}</pre></body></html>"


if __name__ == "__main__":
    main()
