"""Experiment 1 — Market selection on thin/illiquid markets (EdgeHuntPlan.md).

Mac-runnable against the local archive. Segments the resolved set into liquidity
tiers and measures calibration (implied YES probability vs realized outcome) per
tier, looking for a consistent-sign mispricing in the illiquid quartile.

================================ PRE-REGISTERED ================================

PREDICTION (stated before running, per WORKING PROTOCOL #2):
  The calibration gap  =  mean(implied YES prob) - mean(realized YES outcome)
  worsens MONOTONICALLY as liquidity falls. The least-liquid quartile shows
  |gap| > 0.05 with a CONSISTENT SIGN within venue/category — i.e. the illiquid
  markets are mispriced in a predictable direction we could bet.

KILL CONDITION (-> mark DEAD in RESEARCH_LOG.md as Entry 24 if EITHER holds):
  (a) |gap| does NOT increase monotonically from the most-liquid to the
      least-liquid tier (illiquidity does not degrade calibration), OR
  (b) the least-liquid quartile's mispricing has inconsistent sign across
      venue/category (we cannot predict the direction).

DISCIPLINE:
  - A positive result at small n is presumed overfit (PROTOCOL #3). If the clean
    sample is below --min-sample the verdict is INCONCLUSIVE, not SIGNAL.
  - A kill is a SUCCESS of the process (PROTOCOL #4): it closes Experiment 1.
  - Whichever way it lands, paste the SUMMARY block below into Entry 24.

===============================================================================

Usage:
  .venv/bin/python scripts/experiment_01_liquidity_calibration.py
  (reads $PM_EDGE_LOCAL_RESOLVED_DIR and $PM_EDGE_LOCAL_FORWARD_INDEX_DIR;
   override with --resolved-dir / --forward-index-dir)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

import duckdb  # type: ignore[import-untyped]
import pandas as pd

# Pre-registered thresholds (do not tune after seeing results).
GAP_THRESHOLD = 0.05
N_TIERS = 4
MAX_LAG_HOURS = 4.0
MIN_SAMPLE = 60  # below this the experiment is INCONCLUSIVE, not a verdict
MIN_GROUP_N = 10  # min markets for a venue/category to count in the sign check

VERDICT_SIGNAL = "SIGNAL (candidate edge — proceed to cost/backtest)"
VERDICT_DEAD = "DEAD (kill condition met — close Experiment 1)"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE (insufficient clean sample — collect more)"


@dataclass
class Result:
    """Everything needed to render the Entry-24 summary block."""

    n_total: int
    n_clean: int
    tiers: pd.DataFrame
    monotonic: bool
    bottom_abs_gap: float
    bottom_sign_consistent: bool
    bottom_by_category: pd.DataFrame
    overall_brier: float
    verdict: str
    reasons: list[str] = field(default_factory=list)


def _sql_str(value: str) -> str:
    """Quote a path for safe inline use in a DuckDB SQL string literal."""

    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def load_clean_markets(
    resolved_glob: str,
    metadata_glob: str,
    *,
    max_lag_hours: float,
) -> tuple[pd.DataFrame, int]:
    """Return (clean per-market frame, total resolutions with a usable final book).

    One row per resolved market with: venue, market_id, implied_prob, outcome,
    lag_hours, volume_24h, liquidity, category. ``hive_partitioning=false`` is
    set deliberately: the parquet lives under ``venue=.../date=.../`` paths and
    also carries a ``venue`` column, so hive inference would collide on ``venue``.
    """

    con = duckdb.connect()
    sql = f"""
        WITH resolved AS (
            SELECT
                venue,
                market_id,
                resolved_value AS outcome,
                final_top_bid,
                final_top_ask,
                coalesce(venue_resolved_at_utc, resolution_timestamp_utc) AS res_ts,
                final_snapshot_timestamp_utc AS final_ts
            FROM read_parquet({_sql_str(resolved_glob)},
                              hive_partitioning=false, union_by_name=true)
        ),
        meta AS (
            SELECT venue, market_id, captured_at_utc, volume_24h, liquidity, raw_json
            FROM read_parquet({_sql_str(metadata_glob)},
                              hive_partitioning=false, union_by_name=true)
        ),
        meta_at_res AS (
            SELECT
                r.venue,
                r.market_id,
                m.volume_24h,
                m.liquidity,
                m.raw_json,
                row_number() OVER (
                    PARTITION BY r.venue, r.market_id ORDER BY m.captured_at_utc DESC
                ) AS rn
            FROM resolved r
            JOIN meta m
              ON m.venue = r.venue
             AND m.market_id = r.market_id
             AND m.captured_at_utc <= r.res_ts
        )
        SELECT
            r.venue,
            r.market_id,
            (r.final_top_bid + r.final_top_ask) / 2.0 AS implied_prob,
            r.outcome,
            date_diff('second', r.final_ts, r.res_ts) / 3600.0 AS lag_hours,
            mr.volume_24h,
            mr.liquidity,
            CASE
                WHEN r.venue = 'polymarket'
                    THEN coalesce(
                        nullif(lower(json_extract_string(mr.raw_json, '$.feeType')), ''),
                        'polymarket_uncat'
                    )
                ELSE r.venue
            END AS category
        FROM resolved r
        LEFT JOIN meta_at_res mr
          ON mr.venue = r.venue AND mr.market_id = r.market_id AND mr.rn = 1
        WHERE r.final_top_bid IS NOT NULL AND r.final_top_ask IS NOT NULL
    """
    raw = con.execute(sql).fetch_df()
    con.close()

    n_total = len(raw)
    clean = raw[
        raw["lag_hours"].between(0.0, max_lag_hours)
        & raw["implied_prob"].between(0.0, 1.0, inclusive="neither")
        & raw["outcome"].notna()
        & raw["volume_24h"].notna()
        & (raw["volume_24h"] > 0)
    ].copy()
    clean["outcome"] = clean["outcome"].clip(0.0, 1.0)
    return clean, n_total


def assign_tiers(df: pd.DataFrame, *, n_tiers: int) -> pd.DataFrame:
    """Add a ``tier`` column (1 = most liquid ... n = least liquid) by volume."""

    out = df.copy()
    # Rank-based qcut gives equal-sized tiers even with many tied volumes.
    ranks = out["volume_24h"].rank(method="first")
    out["tier"] = pd.qcut(ranks, n_tiers, labels=list(range(1, n_tiers + 1)))
    out["tier"] = n_tiers + 1 - out["tier"].astype(int)  # flip so high tier = illiquid
    return out


def tier_calibration(df: pd.DataFrame) -> pd.DataFrame:
    """Per-tier calibration table, ordered most-liquid (1) to least-liquid (n)."""

    def _agg(group: pd.DataFrame) -> pd.Series:
        implied = group["implied_prob"]
        outcome = group["outcome"]
        gap = implied.mean() - outcome.mean()
        return pd.Series(
            {
                "n": len(group),
                "volume_p50": group["volume_24h"].median(),
                "mean_implied": implied.mean(),
                "mean_outcome": outcome.mean(),
                "gap": gap,
                "abs_gap": abs(gap),
                "brier": ((implied - outcome) ** 2).mean(),
            }
        )

    table = df.groupby("tier", observed=True).apply(_agg, include_groups=False)
    return table.sort_index()


def _sign_consistency(bottom: pd.DataFrame, *, min_group_n: int) -> tuple[bool, pd.DataFrame]:
    """Return (consistent?, per-category gap table) for the least-liquid tier."""

    rows = []
    for category, group in bottom.groupby("category", observed=True):
        gap = group["implied_prob"].mean() - group["outcome"].mean()
        rows.append(
            {
                "category": category,
                "n": len(group),
                "gap": gap,
                "sign": "+" if gap > 0 else "-" if gap < 0 else "0",
            }
        )
    by_category = pd.DataFrame(rows).sort_values("n", ascending=False)
    sizeable = by_category[by_category["n"] >= min_group_n]
    if sizeable.empty:
        return False, by_category
    signs = {s for s in sizeable["sign"] if s != "0"}
    return (len(signs) == 1), by_category


def evaluate(
    df: pd.DataFrame,
    n_total: int,
    *,
    n_tiers: int = N_TIERS,
    gap_threshold: float = GAP_THRESHOLD,
    min_sample: int = MIN_SAMPLE,
    min_group_n: int = MIN_GROUP_N,
) -> Result:
    """Apply the pre-registered prediction and kill condition to the clean set."""

    n_clean = len(df)
    if n_clean < min_sample:
        return Result(
            n_total=n_total,
            n_clean=n_clean,
            tiers=pd.DataFrame(),
            monotonic=False,
            bottom_abs_gap=float("nan"),
            bottom_sign_consistent=False,
            bottom_by_category=pd.DataFrame(),
            overall_brier=float("nan"),
            verdict=VERDICT_INCONCLUSIVE,
            reasons=[f"clean n={n_clean} < min_sample={min_sample}"],
        )

    tiered = assign_tiers(df, n_tiers=n_tiers)
    tiers = tier_calibration(tiered)

    abs_gaps = tiers["abs_gap"].tolist()  # most-liquid -> least-liquid
    monotonic = all(b >= a - 1e-9 for a, b in zip(abs_gaps, abs_gaps[1:], strict=False))

    bottom = tiered[tiered["tier"] == tiers.index.max()]
    bottom_abs_gap = abs(bottom["implied_prob"].mean() - bottom["outcome"].mean())
    sign_consistent, by_category = _sign_consistency(bottom, min_group_n=min_group_n)
    overall_brier = ((df["implied_prob"] - df["outcome"]) ** 2).mean()

    reasons: list[str] = []
    if not monotonic:
        reasons.append("|gap| does not worsen monotonically toward illiquid tiers")
    if bottom_abs_gap <= gap_threshold:
        reasons.append(f"least-liquid |gap|={bottom_abs_gap:.4f} <= {gap_threshold}")
    if not sign_consistent:
        reasons.append("least-liquid mispricing sign is inconsistent across categories")

    verdict = VERDICT_SIGNAL if not reasons else VERDICT_DEAD
    return Result(
        n_total=n_total,
        n_clean=n_clean,
        tiers=tiers,
        monotonic=monotonic,
        bottom_abs_gap=bottom_abs_gap,
        bottom_sign_consistent=sign_consistent,
        bottom_by_category=by_category,
        overall_brier=overall_brier,
        verdict=verdict,
        reasons=reasons,
    )


def format_summary(result: Result, *, max_lag_hours: float) -> str:
    """Render an Entry-24-ready summary block."""

    lines = [
        "=" * 78,
        "EXPERIMENT 1 — Liquidity-tier calibration  (paste into RESEARCH_LOG.md)",
        "=" * 78,
        f"Resolutions with usable final book : {result.n_total}",
        f"Clean (lag in [0,{max_lag_hours}h], 0<implied<1, volume>0): {result.n_clean}",
        "",
    ]
    if result.tiers.empty:
        lines.append(f"VERDICT: {result.verdict}")
        lines.extend(f"  - {r}" for r in result.reasons)
        lines.append("=" * 78)
        return "\n".join(lines)

    lines.append("Per tier (1 = most liquid ... highest = least liquid):")
    table = result.tiers.copy()
    for col in ("volume_p50", "mean_implied", "mean_outcome", "gap", "abs_gap", "brier"):
        table[col] = table[col].map(lambda v: f"{v:.4f}")
    table["n"] = result.tiers["n"].astype(int)
    lines.append(table.to_string())
    lines.append("")
    lines.append(f"Monotonic |gap| worsening toward illiquid : {result.monotonic}")
    lines.append(f"Least-liquid tier |gap|                   : {result.bottom_abs_gap:.4f}")
    lines.append(f"Least-liquid sign consistent by category  : {result.bottom_sign_consistent}")
    lines.append(f"Overall Brier                             : {result.overall_brier:.4f}")
    lines.append("")
    lines.append("Least-liquid tier gap by category:")
    lines.append(result.bottom_by_category.to_string(index=False))
    lines.append("")
    lines.append(f"VERDICT: {result.verdict}")
    for reason in result.reasons:
        lines.append(f"  - {reason}")
    lines.append("=" * 78)
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolved-dir",
        type=Path,
        default=os.environ.get("PM_EDGE_LOCAL_RESOLVED_DIR"),
        help="Resolved-outcomes archive root (default $PM_EDGE_LOCAL_RESOLVED_DIR).",
    )
    parser.add_argument(
        "--forward-index-dir",
        type=Path,
        default=os.environ.get("PM_EDGE_LOCAL_FORWARD_INDEX_DIR"),
        help="Forward-index archive root (default $PM_EDGE_LOCAL_FORWARD_INDEX_DIR).",
    )
    parser.add_argument("--max-lag-hours", type=float, default=MAX_LAG_HOURS)
    parser.add_argument("--tiers", type=int, default=N_TIERS)
    parser.add_argument("--gap-threshold", type=float, default=GAP_THRESHOLD)
    parser.add_argument("--min-sample", type=int, default=MIN_SAMPLE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.resolved_dir is None or args.forward_index_dir is None:
        raise SystemExit(
            "Set PM_EDGE_LOCAL_RESOLVED_DIR and PM_EDGE_LOCAL_FORWARD_INDEX_DIR "
            "(or pass --resolved-dir / --forward-index-dir)."
        )
    resolved_glob = str(Path(args.resolved_dir) / "**" / "*.parquet")
    metadata_glob = str(
        Path(args.forward_index_dir) / "market_metadata_snapshots" / "**" / "*.parquet"
    )
    clean, n_total = load_clean_markets(
        resolved_glob, metadata_glob, max_lag_hours=args.max_lag_hours
    )
    result = evaluate(
        clean,
        n_total,
        n_tiers=args.tiers,
        gap_threshold=args.gap_threshold,
        min_sample=args.min_sample,
    )
    print(format_summary(result, max_lag_hours=args.max_lag_hours))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
