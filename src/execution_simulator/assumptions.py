"""Empirical validation checks for simulator assumptions."""

from __future__ import annotations

from pathlib import Path

import duckdb

from .config import SimulatorConfig
from .types import AssumptionReport, AssumptionResult


def run_all(
    archive_path: Path,
    *,
    max_book_age_seconds: int | None = None,
) -> AssumptionReport:
    """Run all v0 assumption checks against a local forward-index archive."""

    active_max_age = (
        SimulatorConfig().max_book_age_seconds
        if max_book_age_seconds is None
        else max_book_age_seconds
    )
    con = duckdb.connect()
    _create_views(con, archive_path.expanduser())
    results = [
        top_of_book_completeness(con),
        trade_within_spread_rate(con, max_book_age_seconds=active_max_age),
        book_staleness_rate(con),
        bid_ask_cross_rate(con),
        depth_dependency_rate(con),
    ]
    con.close()
    return AssumptionReport(results=results)


def top_of_book_completeness(con: duckdb.DuckDBPyConnection) -> AssumptionResult:
    value = _scalar(
        con,
        """
        SELECT avg(CASE WHEN top_bid IS NOT NULL AND top_ask IS NOT NULL THEN 1.0 ELSE 0.0 END)
        FROM order_book_snapshots
        """,
    )
    return AssumptionResult(
        name="top_of_book_completeness",
        empirical_value=value,
        threshold=0.70,
        passed=value is not None and value > 0.70,
        note="Marketable fill modeling needs both top bid and top ask populated.",
    )


def trade_within_spread_rate(
    con: duckdb.DuckDBPyConnection,
    *,
    max_book_age_seconds: int | None = None,
) -> AssumptionResult:
    active_max_age = (
        SimulatorConfig().max_book_age_seconds
        if max_book_age_seconds is None
        else max_book_age_seconds
    )
    row = con.execute(
        """
        WITH joined AS (
            SELECT
                t.price,
                s.top_bid,
                s.top_ask,
                date_diff('second', s.timestamp_utc, t.timestamp_utc) AS snapshot_age_seconds
            FROM trade_events t
            LEFT JOIN LATERAL (
                SELECT timestamp_utc, top_bid, top_ask
                FROM order_book_snapshots s
                WHERE s.venue = t.venue
                  AND s.market_id = t.market_id
                  AND s.timestamp_utc <= t.timestamp_utc
                ORDER BY s.timestamp_utc DESC
                LIMIT 1
            ) s ON true
        )
        SELECT
            count(*) AS total,
            sum(
                CASE
                    WHEN top_bid IS NOT NULL
                     AND top_ask IS NOT NULL
                     AND snapshot_age_seconds <= ?
                    THEN 1 ELSE 0
                END
            ) AS filtered,
            sum(
                CASE
                    WHEN top_bid IS NOT NULL
                     AND top_ask IS NOT NULL
                     AND snapshot_age_seconds <= ?
                     AND price BETWEEN top_bid AND top_ask
                    THEN 1 ELSE 0
                END
            ) AS inside
        FROM joined
        """,
        [active_max_age, active_max_age],
    ).fetchone()
    total = 0 if row is None else int(row[0] or 0)
    filtered = 0 if row is None else int(row[1] or 0)
    inside = 0 if row is None else int(row[2] or 0)
    excluded = total - filtered
    value = None if filtered == 0 else inside / filtered
    return AssumptionResult(
        name="trade_within_spread_rate",
        empirical_value=value,
        threshold=0.80,
        passed=value is not None and value > 0.80,
        note=(
            "Trade prices should usually be consistent with contemporaneous book state. "
            f"total_trades={total}, filtered_trades={filtered}, "
            f"excluded_trades={excluded}, max_book_age_seconds={active_max_age}."
        ),
    )


def book_staleness_rate(
    con: duckdb.DuckDBPyConnection,
    *,
    max_age_seconds: int = 60,
) -> AssumptionResult:
    row = con.execute(
        """
        WITH per_minute AS (
            SELECT
                venue,
                market_id,
                time_bucket(INTERVAL '1 minute', timestamp_utc) AS bucket,
                max(timestamp_utc) AS latest_in_bucket
            FROM order_book_snapshots
            GROUP BY venue, market_id, bucket
        )
        SELECT
            count(*) AS total,
            sum(
                CASE
                    WHEN date_diff('second', latest_in_bucket, bucket + INTERVAL '1 minute') > ?
                    THEN 1 ELSE 0
                END
            ) AS stale
        FROM per_minute
        """,
        [max_age_seconds],
    ).fetchone()
    total = 0 if row is None else int(row[0] or 0)
    stale = 0 if row is None else int(row[1] or 0)
    value = None if total == 0 else stale / total
    return AssumptionResult(
        name="book_staleness_rate",
        empirical_value=value,
        threshold=0.10,
        passed=value is not None and value < 0.10,
        note="Orders are rejected when the most recent book is older than the v0 freshness cap.",
    )


def bid_ask_cross_rate(con: duckdb.DuckDBPyConnection) -> AssumptionResult:
    value = _scalar(
        con,
        """
        SELECT avg(CASE WHEN top_bid > top_ask THEN 1.0 ELSE 0.0 END)
        FROM order_book_snapshots
        WHERE top_bid IS NOT NULL AND top_ask IS NOT NULL
        """,
    )
    return AssumptionResult(
        name="bid_ask_cross_rate",
        empirical_value=value,
        threshold=0.001,
        passed=value is not None and value < 0.001,
        note="Crossed books indicate anomalous state that v0 does not try to repair.",
    )


def depth_dependency_rate(con: duckdb.DuckDBPyConnection) -> AssumptionResult:
    row = con.execute("""
        WITH joined AS (
            SELECT
                t.size,
                lower(coalesce(t.side, '')) AS side,
                s.bid_levels,
                s.ask_levels
            FROM trade_events t
            LEFT JOIN LATERAL (
                SELECT bid_levels, ask_levels
                FROM order_book_snapshots s
                WHERE s.venue = t.venue
                  AND s.market_id = t.market_id
                  AND s.timestamp_utc <= t.timestamp_utc
                ORDER BY s.timestamp_utc DESC
                LIMIT 1
            ) s ON true
        ),
        top_sizes AS (
            SELECT
                size,
                CASE
                    WHEN side = 'buy' THEN ask_levels[1].size
                    WHEN side = 'sell' THEN bid_levels[1].size
                    ELSE greatest(
                        coalesce(ask_levels[1].size, 0),
                        coalesce(bid_levels[1].size, 0)
                    )
                END AS top_level_size
            FROM joined
            WHERE bid_levels IS NOT NULL OR ask_levels IS NOT NULL
        )
        SELECT
            count(*) AS total,
            sum(CASE WHEN size > top_level_size THEN 1 ELSE 0 END) AS needs_depth
        FROM top_sizes
        WHERE top_level_size IS NOT NULL
        """).fetchone()
    total = 0 if row is None else int(row[0] or 0)
    needs_depth = 0 if row is None else int(row[1] or 0)
    value = None if total == 0 else needs_depth / total
    return AssumptionResult(
        name="depth_gt_1_dependency_rate",
        empirical_value=value,
        threshold=0.20,
        passed=value is not None and value < 0.20,
        note="v0 only fills against level 1, so large orders are intentionally underfilled.",
    )


def _create_views(con: duckdb.DuckDBPyConnection, archive_path: Path) -> None:
    _create_table_or_empty(
        con,
        "order_book_snapshots",
        archive_path,
        """
        SELECT
            CAST(NULL AS VARCHAR) AS venue,
            CAST(NULL AS VARCHAR) AS market_id,
            CAST(NULL AS TIMESTAMPTZ) AS timestamp_utc,
            CAST([] AS STRUCT(price DOUBLE, size DOUBLE)[]) AS bid_levels,
            CAST([] AS STRUCT(price DOUBLE, size DOUBLE)[]) AS ask_levels,
            CAST(NULL AS DOUBLE) AS top_bid,
            CAST(NULL AS DOUBLE) AS top_ask
        WHERE false
        """,
    )
    _create_table_or_empty(
        con,
        "trade_events",
        archive_path,
        """
        SELECT
            CAST(NULL AS VARCHAR) AS venue,
            CAST(NULL AS VARCHAR) AS market_id,
            CAST(NULL AS TIMESTAMPTZ) AS timestamp_utc,
            CAST(NULL AS DOUBLE) AS price,
            CAST(NULL AS DOUBLE) AS size,
            CAST(NULL AS VARCHAR) AS side
        WHERE false
        """,
    )


def _create_table_or_empty(
    con: duckdb.DuckDBPyConnection,
    table: str,
    archive_path: Path,
    empty_sql: str,
) -> None:
    table_dir = archive_path / table
    if table_dir.exists() and any(table_dir.rglob("*.parquet")):
        glob_path = _sql_string(str(table_dir / "**" / "*.parquet"))
        con.execute(
            f"CREATE OR REPLACE TEMP VIEW {table} AS SELECT * FROM read_parquet({glob_path})"
        )
        return
    con.execute(f"CREATE OR REPLACE TEMP VIEW {table} AS {empty_sql}")


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> float | None:
    row = con.execute(sql).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
