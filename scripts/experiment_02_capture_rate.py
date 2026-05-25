"""Experiment 2 — hi-cad near-resolution capture-RATE check (NOT the analysis).

Mac-runnable against the local archive, same pattern as
``scripts/experiment_01_liquidity_calibration.py``. Read-only: it measures how
fast usable hi-cad near-resolution events are accumulating so we can project
whether the ~150-clean-event target is ~2 weeks out or ~6, and decide whether a
~15%-prior experiment is worth the wait. Run it ~48h after enabling hi-cad
capture, and again periodically.

A "usable hi-cad event" = a market that has >=1 snapshot tagged
``snapshot_source='near_resolution_hicad'`` AND is resolved with
``resolved_value IN (0.0, 1.0)``. Hi-cad snapshots for markets that have not
resolved (yet) are captured-but-unusable — counted separately, not toward the
target.

This is the rate-measurement GATE for deciding Experiment 2's duration. It is NOT
the Experiment 2 analysis (does the price lead/lag the event) — that comes later.

Usage:
  .venv/bin/python scripts/experiment_02_capture_rate.py
  (reads $PM_EDGE_LOCAL_FORWARD_INDEX_DIR and $PM_EDGE_LOCAL_RESOLVED_DIR;
   override with --forward-index-dir / --resolved-dir / --venue / --days-elapsed)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb  # type: ignore[import-untyped]
import pandas as pd

HICAD_SOURCE = "near_resolution_hicad"
DEFAULT_TARGET = 150
DEFAULT_VENUE = "kalshi"


@dataclass
class CaptureStats:
    """Raw counts from the archive; everything else is derived from these."""

    daily: pd.DataFrame  # columns: day, hicad_snapshots
    per_market: pd.DataFrame  # columns: market_id, hicad_snapshots, span_seconds, is_resolved

    @property
    def total_snapshots(self) -> int:
        return int(self.per_market["hicad_snapshots"].sum()) if not self.per_market.empty else 0

    @property
    def distinct_markets(self) -> int:
        return int(len(self.per_market))

    @property
    def usable_events(self) -> pd.DataFrame:
        if self.per_market.empty:
            return self.per_market
        return self.per_market[self.per_market["is_resolved"]]

    @property
    def usable_event_count(self) -> int:
        return int(len(self.usable_events))

    @property
    def unresolved_count(self) -> int:
        return self.distinct_markets - self.usable_event_count

    @property
    def earliest_day(self) -> date | None:
        if self.daily.empty:
            return None
        ts = pd.to_datetime(self.daily["day"]).min()
        return date(ts.year, ts.month, ts.day)


def _sql_str(value: str) -> str:
    """Quote a path for safe inline use in a DuckDB SQL string literal."""

    return "'" + value.replace("'", "''") + "'"


def _require_parquet(directory: Path, label: str, env_var: str) -> None:
    if not directory.is_dir() or not any(directory.rglob("*.parquet")):
        raise FileNotFoundError(
            f"No {label} parquet found under {directory}; set {env_var} (or pass the "
            f"matching --*-dir) and confirm the archive is synced. Expected "
            f"{directory / '**' / '*.parquet'}."
        )


def load_capture_stats(
    hicad_glob: str,
    resolved_glob: str,
    *,
    hicad_source: str = HICAD_SOURCE,
) -> CaptureStats:
    """Measure hi-cad capture from the archive. Read-only.

    ``hive_partitioning=false`` because the parquet lives under
    ``venue=.../date=.../`` paths and also carries a ``venue`` column — hive
    inference would collide on ``venue``. ``union_by_name=true`` tolerates the
    evolved schema (older parquet has fewer columns).
    """

    con = duckdb.connect()
    daily = con.execute(
        f"""
        SELECT CAST(timestamp_utc AS DATE) AS day, count(*) AS hicad_snapshots
        FROM read_parquet({_sql_str(hicad_glob)}, union_by_name=true, hive_partitioning=false)
        WHERE snapshot_source = ?
        GROUP BY 1
        ORDER BY 1
        """,
        [hicad_source],
    ).fetchdf()

    per_market = con.execute(
        f"""
        WITH hicad AS (
            SELECT market_id, timestamp_utc
            FROM read_parquet({_sql_str(hicad_glob)},
                              union_by_name=true, hive_partitioning=false)
            WHERE snapshot_source = ?
        ),
        resolved AS (
            SELECT DISTINCT market_id
            FROM read_parquet({_sql_str(resolved_glob)},
                              union_by_name=true, hive_partitioning=false)
            WHERE resolved_value IN (0.0, 1.0)
        ),
        per_market AS (
            SELECT
                market_id,
                count(*) AS hicad_snapshots,
                date_diff('second', min(timestamp_utc), max(timestamp_utc)) AS span_seconds
            FROM hicad
            GROUP BY market_id
        )
        SELECT
            pm.market_id,
            pm.hicad_snapshots,
            pm.span_seconds,
            (r.market_id IS NOT NULL) AS is_resolved
        FROM per_market pm
        LEFT JOIN resolved r ON r.market_id = pm.market_id
        ORDER BY pm.hicad_snapshots DESC
        """,
        [hicad_source],
    ).fetchdf()
    con.close()
    return CaptureStats(daily=daily, per_market=per_market)


def infer_days_elapsed(earliest_day: date | None, today: date) -> int:
    """Inclusive day count from the first hi-cad capture to ``today`` (>=0)."""

    if earliest_day is None:
        return 0
    return max(1, (today - earliest_day).days + 1)


def project(usable_events: int, days_elapsed: int, target: int) -> tuple[float, float | None]:
    """Return (events_per_day, days_to_target). days_to_target is None if rate==0."""

    rate = usable_events / days_elapsed if days_elapsed > 0 else 0.0
    if rate <= 0:
        return rate, None
    remaining = max(0, target - usable_events)
    return rate, remaining / rate


def format_summary(
    stats: CaptureStats,
    *,
    days_elapsed: int,
    target: int,
    venue: str,
) -> str:
    """Render a plain capture-rate report."""

    rate, days_to_target = project(stats.usable_event_count, days_elapsed, target)
    lines = [
        "=" * 78,
        f"EXPERIMENT 2 — hi-cad capture-rate check (venue={venue})",
        "rate-measurement gate for Exp 2 duration; NOT the Exp 2 analysis",
        "=" * 78,
        "",
        "Daily hi-cad snapshots captured:",
    ]
    if stats.daily.empty:
        lines.append("  (none)")
    else:
        for _, row in stats.daily.iterrows():
            day = pd.to_datetime(row["day"]).date()
            lines.append(f"  {day}: {int(row['hicad_snapshots'])}")

    lines += [
        "",
        f"Total hi-cad snapshots         : {stats.total_snapshots}",
        f"Distinct markets with hi-cad   : {stats.distinct_markets}",
        f"  -> usable (resolved 0/1)     : {stats.usable_event_count}",
        f"  -> captured-but-unresolved   : {stats.unresolved_count}",
        "",
    ]

    usable = stats.usable_events
    if usable.empty:
        lines.append("Per usable-event density: (no usable events yet)")
    else:
        snaps = usable["hicad_snapshots"]
        span_min = usable["span_seconds"] / 60.0
        lines.append("Per usable-event density (are we capturing the window, or a few frames?):")
        lines.append(
            f"  hi-cad snapshots/event : median {snaps.median():.0f}  "
            f"min {int(snaps.min())}  max {int(snaps.max())}"
        )
        lines.append(
            f"  window span (minutes)  : median {span_min.median():.1f}  "
            f"min {span_min.min():.1f}  max {span_min.max():.1f}"
        )

    lines += [
        "",
        "PROJECTION:",
        f"  days elapsed           : {days_elapsed}",
        f"  usable events so far   : {stats.usable_event_count}",
        f"  events/day             : {rate:.2f}",
    ]
    if days_to_target is None:
        lines.append(
            f"  days to {target} events    : N/A (rate is 0 — capture nothing yet, or none resolved)"
        )
    elif days_to_target == 0:
        lines.append(f"  days to {target} events    : 0 (target already met)")
    else:
        lines.append(
            f"  days to {target} events    : {days_to_target:.1f}  "
            f"(~{days_to_target / 7.0:.1f} weeks)"
        )
    lines.append("=" * 78)
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--forward-index-dir",
        type=Path,
        default=os.environ.get("PM_EDGE_LOCAL_FORWARD_INDEX_DIR"),
        help="Forward-index archive root (default $PM_EDGE_LOCAL_FORWARD_INDEX_DIR).",
    )
    parser.add_argument(
        "--resolved-dir",
        type=Path,
        default=os.environ.get("PM_EDGE_LOCAL_RESOLVED_DIR"),
        help="Resolved-outcomes archive root (default $PM_EDGE_LOCAL_RESOLVED_DIR).",
    )
    parser.add_argument(
        "--venue", default=DEFAULT_VENUE, help="Venue to scope to (default kalshi)."
    )
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET)
    parser.add_argument(
        "--days-elapsed",
        type=int,
        default=None,
        help="Override the projection denominator (default: infer from earliest hi-cad date).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.forward_index_dir is None or args.resolved_dir is None:
        raise SystemExit(
            "Set PM_EDGE_LOCAL_FORWARD_INDEX_DIR and PM_EDGE_LOCAL_RESOLVED_DIR "
            "(or pass --forward-index-dir / --resolved-dir)."
        )
    hicad_base = Path(args.forward_index_dir) / "order_book_snapshots" / f"venue={args.venue}"
    resolved_base = Path(args.resolved_dir) / f"venue={args.venue}"
    _require_parquet(hicad_base, "order-book snapshot", "PM_EDGE_LOCAL_FORWARD_INDEX_DIR")
    _require_parquet(resolved_base, "resolved-outcome", "PM_EDGE_LOCAL_RESOLVED_DIR")

    stats = load_capture_stats(
        str(hicad_base / "**" / "*.parquet"),
        str(resolved_base / "**" / "*.parquet"),
    )
    days_elapsed = (
        args.days_elapsed
        if args.days_elapsed is not None
        else infer_days_elapsed(stats.earliest_day, datetime.now(tz=UTC).date())
    )
    print(format_summary(stats, days_elapsed=days_elapsed, target=args.target, venue=args.venue))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
