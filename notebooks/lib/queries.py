"""Reusable DuckDB queries for forward-indexer parquet archives."""

from __future__ import annotations

import os
import re
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd

DEFAULT_DATA_DIR = Path("~/pm-edge-data/forward_index").expanduser()
DATA_DIR_ENV = "PM_EDGE_LOCAL_FORWARD_INDEX_DIR"
EXPECTED_TABLES = ("order_book_snapshots", "trade_events", "market_metadata_snapshots")

TIMESCALE_RE = re.compile(r"^\d+\s+(minute|hour|day)s?$")


def get_connection(data_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection configured to read the local parquet archive.

    `data_dir` defaults to the PM_EDGE_LOCAL_FORWARD_INDEX_DIR environment variable,
    or ~/pm-edge-data/forward_index if not set.
    """

    root, source = _resolve_data_dir(data_dir)
    _validate_data_dir(root, source)
    con = duckdb.connect()
    _create_forward_index_views(con, root)
    return con


def hourly_snapshot_volume(
    con: duckdb.DuckDBPyConnection,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Snapshots per hour, optionally filtered by venue and time range.

    Returns columns: venue, hour, snapshots, distinct_markets.
    """

    where, params = _time_filters("timestamp_utc", venue=venue, since=since, until=until)
    sql = f"""
        SELECT
            venue,
            date_trunc('hour', timestamp_utc) AS hour,
            count(*) AS snapshots,
            count(DISTINCT market_id) AS distinct_markets
        FROM order_book_snapshots
        WHERE {where}
        GROUP BY venue, hour
        ORDER BY hour, venue
    """
    return _fetch_df(con, sql, params)


def source_breakdown(
    con: duckdb.DuckDBPyConnection,
    since: datetime | None = None,
) -> pd.DataFrame:
    """Snapshot source distribution by venue.

    Returns columns: venue, snapshot_source, count, pct_of_venue.
    """

    where, params = _time_filters("timestamp_utc", since=since)
    sql = f"""
        WITH counts AS (
            SELECT venue, snapshot_source, count(*) AS count
            FROM order_book_snapshots
            WHERE {where}
            GROUP BY venue, snapshot_source
        )
        SELECT
            venue,
            snapshot_source,
            count,
            count::DOUBLE / sum(count) OVER (PARTITION BY venue) AS pct_of_venue
        FROM counts
        ORDER BY venue, count DESC
    """
    return _fetch_df(con, sql, params)


def book_state_quality(
    con: duckdb.DuckDBPyConnection,
    venue: str,
    since: datetime | None = None,
) -> pd.DataFrame:
    """Book state quality metrics for a venue.

    Returns columns: snapshots, avg_bid_levels, avg_ask_levels,
    pct_with_top_bid, pct_with_top_ask, mean_top_bid, mean_top_ask.
    """

    where, params = _time_filters("timestamp_utc", venue=venue, since=since)
    sql = f"""
        SELECT
            count(*) AS snapshots,
            avg(len(bid_levels)) AS avg_bid_levels,
            avg(len(ask_levels)) AS avg_ask_levels,
            avg(CASE WHEN top_bid IS NOT NULL THEN 1.0 ELSE 0.0 END) AS pct_with_top_bid,
            avg(CASE WHEN top_ask IS NOT NULL THEN 1.0 ELSE 0.0 END) AS pct_with_top_ask,
            avg(top_bid) AS mean_top_bid,
            avg(top_ask) AS mean_top_ask
        FROM order_book_snapshots
        WHERE {where}
    """
    return _fetch_df(con, sql, params)


def capture_freshness(
    con: duckdb.DuckDBPyConnection,
    *,
    now: datetime | None = None,
    expected_cadence_seconds: int = 15,
    venue: str | None = None,
) -> pd.DataFrame:
    """Latest snapshot and rough cadence completeness by venue.

    Returns columns: venue, first_snapshot_utc, latest_snapshot_utc,
    snapshot_age_minutes, snapshots, distinct_markets, observed_hours,
    expected_snapshots_at_cadence, pct_expected_snapshots.
    """

    reference_time = now or datetime.now(UTC)
    where, params = _time_filters("timestamp_utc", venue=venue)
    sql = f"""
        WITH per_venue AS (
            SELECT
                venue,
                min(timestamp_utc) AS first_snapshot_utc,
                max(timestamp_utc) AS latest_snapshot_utc,
                count(*) AS snapshots,
                count(DISTINCT market_id) AS distinct_markets
            FROM order_book_snapshots
            WHERE {where}
            GROUP BY venue
        )
        SELECT
            venue,
            first_snapshot_utc,
            latest_snapshot_utc,
            date_diff('second', latest_snapshot_utc, ?) / 60.0 AS snapshot_age_minutes,
            snapshots,
            distinct_markets,
            date_diff('second', first_snapshot_utc, latest_snapshot_utc) / 3600.0 AS observed_hours,
            CASE
                WHEN distinct_markets = 0 THEN NULL
                ELSE (
                    date_diff('second', first_snapshot_utc, latest_snapshot_utc)
                    / ?
                    * distinct_markets
                )
            END AS expected_snapshots_at_cadence,
            CASE
                WHEN distinct_markets = 0
                    OR date_diff('second', first_snapshot_utc, latest_snapshot_utc) <= 0
                    THEN NULL
                ELSE snapshots::DOUBLE / (
                    date_diff('second', first_snapshot_utc, latest_snapshot_utc)
                    / ?
                    * distinct_markets
                )
            END AS pct_expected_snapshots
        FROM per_venue
        ORDER BY venue
    """
    return _fetch_df(
        con, sql, [*params, reference_time, expected_cadence_seconds, expected_cadence_seconds]
    )


def snapshot_gaps(
    con: duckdb.DuckDBPyConnection,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    *,
    bucket: str = "5 minutes",
    threshold_ratio: float = 0.5,
) -> pd.DataFrame:
    """Find low-capture time buckets by venue.

    Missing buckets are included as zero-count buckets. A bucket is reported
    when its count is below `threshold_ratio * median(nonzero bucket count)`.
    Returns columns: venue, bucket, snapshot_count, venue_median,
    threshold_count.
    """

    _validate_timescale(bucket)
    where, params = _time_filters("timestamp_utc", venue=venue, since=since, until=until)
    sql = f"""
        WITH filtered AS (
            SELECT venue, timestamp_utc
            FROM order_book_snapshots
            WHERE {where}
        ),
        bounds AS (
            SELECT
                venue,
                time_bucket(INTERVAL '{bucket}', min(timestamp_utc)) AS first_bucket,
                time_bucket(INTERVAL '{bucket}', max(timestamp_utc)) AS last_bucket
            FROM filtered
            GROUP BY venue
        ),
        observed AS (
            SELECT
                venue,
                time_bucket(INTERVAL '{bucket}', timestamp_utc) AS bucket,
                count(*) AS snapshot_count
            FROM filtered
            GROUP BY venue, bucket
        ),
        calendar AS (
            SELECT bounds.venue, series.bucket
            FROM bounds
            CROSS JOIN generate_series(
                bounds.first_bucket,
                bounds.last_bucket,
                INTERVAL '{bucket}'
            ) AS series(bucket)
        ),
        medians AS (
            SELECT venue, median(snapshot_count) AS venue_median
            FROM observed
            WHERE snapshot_count > 0
            GROUP BY venue
        )
        SELECT
            calendar.venue,
            calendar.bucket,
            coalesce(observed.snapshot_count, 0) AS snapshot_count,
            medians.venue_median,
            medians.venue_median * ? AS threshold_count
        FROM calendar
        LEFT JOIN observed
            ON observed.venue = calendar.venue AND observed.bucket = calendar.bucket
        JOIN medians ON medians.venue = calendar.venue
        WHERE coalesce(observed.snapshot_count, 0) < medians.venue_median * ?
        ORDER BY calendar.venue, calendar.bucket
    """
    return _fetch_df(con, sql, [*params, threshold_ratio, threshold_ratio])


def book_validity(
    con: duckdb.DuckDBPyConnection,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Book-state validity checks by venue.

    Returns columns with counts and percentages for crossed books, invalid
    prices, non-positive spreads, empty levels, and both-sided top books.
    """

    where, params = _time_filters("timestamp_utc", venue=venue, since=since, until=until)
    sql = f"""
        SELECT
            venue,
            count(*) AS snapshots,
            sum(CASE WHEN top_bid > top_ask THEN 1 ELSE 0 END) AS crossed_books,
            avg(CASE WHEN top_bid > top_ask THEN 1.0 ELSE 0.0 END) AS pct_crossed_books,
            sum(
                CASE
                    WHEN top_bid < 0 OR top_bid > 1 OR top_ask < 0 OR top_ask > 1
                    THEN 1 ELSE 0
                END
            ) AS invalid_price_rows,
            avg(
                CASE
                    WHEN top_bid < 0 OR top_bid > 1 OR top_ask < 0 OR top_ask > 1
                    THEN 1.0 ELSE 0.0
                END
            ) AS pct_invalid_price_rows,
            sum(CASE WHEN spread <= 0 THEN 1 ELSE 0 END) AS non_positive_spread_rows,
            avg(CASE WHEN spread <= 0 THEN 1.0 ELSE 0.0 END) AS pct_non_positive_spread,
            avg(CASE WHEN len(bid_levels) = 0 THEN 1.0 ELSE 0.0 END) AS pct_empty_bid_levels,
            avg(CASE WHEN len(ask_levels) = 0 THEN 1.0 ELSE 0.0 END) AS pct_empty_ask_levels,
            avg(
                CASE
                    WHEN top_bid IS NOT NULL AND top_ask IS NOT NULL
                    THEN 1.0 ELSE 0.0
                END
            ) AS pct_with_top_both
        FROM order_book_snapshots
        WHERE {where}
        GROUP BY venue
        ORDER BY venue
    """
    return _fetch_df(con, sql, params)


def spread_depth_summary(
    con: duckdb.DuckDBPyConnection,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Spread and depth summary by venue.

    Returns spread quantiles plus average bid/ask depth across captured levels.
    """

    where, params = _time_filters("timestamp_utc", venue=venue, since=since, until=until)
    sql = f"""
        SELECT
            venue,
            count(*) AS snapshots,
            quantile_cont(spread, 0.50) AS spread_p50,
            quantile_cont(spread, 0.90) AS spread_p90,
            quantile_cont(spread, 0.99) AS spread_p99,
            avg(spread) AS spread_mean,
            avg(list_sum(list_transform(bid_levels, level -> level.size))) AS avg_bid_depth,
            avg(list_sum(list_transform(ask_levels, level -> level.size))) AS avg_ask_depth,
            avg(
                list_sum(list_transform(bid_levels, level -> level.size))
                - list_sum(list_transform(ask_levels, level -> level.size))
            ) AS avg_depth_imbalance
        FROM order_book_snapshots
        WHERE {where}
        GROUP BY venue
        ORDER BY venue
    """
    return _fetch_df(con, sql, params)


def market_movement(
    con: duckdb.DuckDBPyConnection,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Per-market movement statistics.

    Returns columns: venue, market_id, snapshots, distinct_top_bids,
    distinct_top_asks, spread_min, spread_max, spread_mean, price_min, price_max.
    """

    where, params = _time_filters("timestamp_utc", venue=venue, since=since, until=until)
    sql = f"""
        SELECT
            venue,
            market_id,
            count(*) AS snapshots,
            count(DISTINCT top_bid) AS distinct_top_bids,
            count(DISTINCT top_ask) AS distinct_top_asks,
            min(spread) AS spread_min,
            max(spread) AS spread_max,
            avg(spread) AS spread_mean,
            min(mid) AS price_min,
            max(mid) AS price_max
        FROM order_book_snapshots
        WHERE {where}
        GROUP BY venue, market_id
        ORDER BY snapshots DESC, venue, market_id
    """
    return _fetch_df(con, sql, params)


def trade_overview(
    con: duckdb.DuckDBPyConnection,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Trade capture summary by venue."""

    where, params = _time_filters("timestamp_utc", venue=venue, since=since, until=until)
    sql = f"""
        WITH filtered AS (
            SELECT *
            FROM trade_events
            WHERE {where}
        ),
        duplicate_ids AS (
            SELECT venue, count(*) AS duplicate_trade_ids
            FROM (
                SELECT venue, trade_id_venue, count(*) AS n
                FROM filtered
                WHERE trade_id_venue IS NOT NULL
                GROUP BY venue, trade_id_venue
                HAVING count(*) > 1
            )
            GROUP BY venue
        )
        SELECT
            filtered.venue,
            count(*) AS trades,
            count(DISTINCT market_id) AS markets_with_trades,
            sum(size) AS contracts,
            sum(price * size) AS notional,
            min(timestamp_utc) AS first_trade_utc,
            max(timestamp_utc) AS latest_trade_utc,
            coalesce(max(duplicate_ids.duplicate_trade_ids), 0) AS duplicate_trade_ids
        FROM filtered
        LEFT JOIN duplicate_ids ON duplicate_ids.venue = filtered.venue
        GROUP BY filtered.venue
        ORDER BY filtered.venue
    """
    return _fetch_df(con, sql, params)


def trade_volume(
    con: duckdb.DuckDBPyConnection,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    groupby: Literal["hour", "day", "market"] = "hour",
) -> pd.DataFrame:
    """Trade volume aggregations.

    Returns columns vary by groupby.
    """

    where, params = _time_filters("timestamp_utc", venue=venue, since=since, until=until)
    if groupby == "hour":
        select_group = "venue, date_trunc('hour', timestamp_utc) AS hour"
        group_clause = "venue, hour"
        order_clause = "hour, venue"
    elif groupby == "day":
        select_group = "venue, date_trunc('day', timestamp_utc) AS day"
        group_clause = "venue, day"
        order_clause = "day, venue"
    elif groupby == "market":
        select_group = "venue, market_id"
        group_clause = "venue, market_id"
        order_clause = "notional DESC, venue, market_id"
    else:
        raise ValueError(f"Unsupported groupby: {groupby}")

    sql = f"""
        SELECT
            {select_group},
            count(*) AS trades,
            sum(size) AS contracts,
            sum(price * size) AS notional
        FROM trade_events
        WHERE {where}
        GROUP BY {group_clause}
        ORDER BY {order_clause}
    """
    return _fetch_df(con, sql, params)


def metadata_universe(
    con: duckdb.DuckDBPyConnection,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Market metadata coverage and liquidity distribution by venue/status."""

    where, params = _time_filters(
        "captured_at_utc",
        venue=venue,
        since=since,
        until=until,
    )
    sql = f"""
        SELECT
            venue,
            status,
            count(*) AS metadata_rows,
            count(DISTINCT market_id) AS markets,
            avg(volume_24h) AS avg_volume_24h,
            quantile_cont(volume_24h, 0.50) AS volume_24h_p50,
            quantile_cont(volume_24h, 0.90) AS volume_24h_p90,
            avg(liquidity) AS avg_liquidity,
            quantile_cont(liquidity, 0.50) AS liquidity_p50,
            avg(date_diff('second', captured_at_utc, end_date) / 3600.0) AS avg_hours_to_close
        FROM market_metadata_snapshots
        WHERE {where}
        GROUP BY venue, status
        ORDER BY venue, status
    """
    return _fetch_df(con, sql, params)


def data_integrity_checks(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return table-level integrity issue counts.

    Returns columns: table_name, check_name, issue_count.
    """

    sql = """
        WITH checks AS (
            SELECT
                'order_book_snapshots' AS table_name,
                'duplicate_snapshot_keys' AS check_name,
                coalesce(sum(n - 1), 0) AS issue_count
            FROM (
                SELECT venue, market_id, timestamp_utc, count(*) AS n
                FROM order_book_snapshots
                GROUP BY venue, market_id, timestamp_utc
                HAVING count(*) > 1
            )
            UNION ALL
            SELECT
                'trade_events',
                'duplicate_trade_ids',
                coalesce(sum(n - 1), 0)
            FROM (
                SELECT venue, trade_id_venue, count(*) AS n
                FROM trade_events
                WHERE trade_id_venue IS NOT NULL
                GROUP BY venue, trade_id_venue
                HAVING count(*) > 1
            )
            UNION ALL
            SELECT
                'order_book_snapshots',
                'null_critical_fields',
                count(*)
            FROM order_book_snapshots
            WHERE venue IS NULL OR market_id IS NULL OR timestamp_utc IS NULL
            UNION ALL
            SELECT
                'trade_events',
                'null_critical_fields',
                count(*)
            FROM trade_events
            WHERE venue IS NULL OR market_id IS NULL OR timestamp_utc IS NULL
            UNION ALL
            SELECT
                'market_metadata_snapshots',
                'null_critical_fields',
                count(*)
            FROM market_metadata_snapshots
            WHERE venue IS NULL OR market_id IS NULL OR captured_at_utc IS NULL
            UNION ALL
            SELECT
                'order_book_snapshots',
                'schema_versions',
                count(DISTINCT schema_version)
            FROM order_book_snapshots
        )
        SELECT table_name, check_name, issue_count
        FROM checks
        ORDER BY table_name, check_name
    """
    return _fetch_df(con, sql)


def analysis_readiness(
    con: duckdb.DuckDBPyConnection,
    *,
    min_snapshots: int = 100,
    min_distinct_top_bids: int = 2,
    max_spread_mean: float = 0.10,
    min_pct_with_top_both: float = 0.95,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Classify markets as ready or not ready for first-pass analysis."""

    where, params = _time_filters("timestamp_utc", venue=venue, since=since, until=until)
    sql = f"""
        WITH per_market AS (
            SELECT
                venue,
                market_id,
                count(*) AS snapshots,
                count(DISTINCT top_bid) AS distinct_top_bids,
                count(DISTINCT top_ask) AS distinct_top_asks,
                avg(spread) AS spread_mean,
                avg(
                    CASE
                        WHEN top_bid IS NOT NULL AND top_ask IS NOT NULL
                        THEN 1.0 ELSE 0.0
                    END
                ) AS pct_with_top_both,
                min(timestamp_utc) AS first_snapshot_utc,
                max(timestamp_utc) AS latest_snapshot_utc
            FROM order_book_snapshots
            WHERE {where}
            GROUP BY venue, market_id
        )
        SELECT
            *,
            CASE
                WHEN snapshots < ? THEN false
                WHEN distinct_top_bids < ? AND distinct_top_asks < ? THEN false
                WHEN spread_mean IS NULL OR spread_mean > ? THEN false
                WHEN pct_with_top_both < ? THEN false
                ELSE true
            END AS is_analysis_ready,
            CASE
                WHEN snapshots < ? THEN 'low_snapshots'
                WHEN distinct_top_bids < ? AND distinct_top_asks < ? THEN 'no_top_book_movement'
                WHEN spread_mean IS NULL OR spread_mean > ? THEN 'wide_or_missing_spread'
                WHEN pct_with_top_both < ? THEN 'incomplete_top_book'
                ELSE 'ready'
            END AS exclusion_reason
        FROM per_market
        ORDER BY is_analysis_ready DESC, snapshots DESC, venue, market_id
    """
    thresholds: list[object] = [
        min_snapshots,
        min_distinct_top_bids,
        min_distinct_top_bids,
        max_spread_mean,
        min_pct_with_top_both,
        min_snapshots,
        min_distinct_top_bids,
        min_distinct_top_bids,
        max_spread_mean,
        min_pct_with_top_both,
    ]
    return _fetch_df(con, sql, [*params, *thresholds])


def multi_timescale_aggregation(
    con: duckdb.DuckDBPyConnection,
    market_id: str,
    timescales: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Return OHLC-style aggregations for one market at multiple timescales.

    Critical for the multi-timescale analysis discipline documented in
    RESEARCH_LOG.md.
    """

    selected = timescales or ["1 minute", "5 minute", "1 hour", "1 day"]
    aggs: dict[str, pd.DataFrame] = {}
    for timescale in selected:
        _validate_timescale(timescale)
        sql = f"""
            WITH bucketed AS (
                SELECT
                    time_bucket(INTERVAL '{timescale}', timestamp_utc) AS bucket,
                    timestamp_utc,
                    top_bid,
                    top_ask,
                    mid,
                    spread
                FROM order_book_snapshots
                WHERE market_id = ?
            )
            SELECT
                bucket,
                arg_min(mid, timestamp_utc) AS mid_open,
                max(mid) AS mid_high,
                min(mid) AS mid_low,
                arg_max(mid, timestamp_utc) AS mid_close,
                avg(mid) AS mid,
                avg(top_bid) AS top_bid,
                avg(top_ask) AS top_ask,
                avg(spread) AS spread,
                count(*) AS snapshots
            FROM bucketed
            GROUP BY bucket
            ORDER BY bucket
        """
        aggs[timescale] = _fetch_df(con, sql, [market_id])
    return aggs


def resolved_market_outcomes(
    con: duckdb.DuckDBPyConnection,
    since: datetime | None = None,
) -> pd.DataFrame:
    """Markets that have resolved within the captured data range.

    Returns columns: venue, market_id, resolution_timestamp, resolved_value,
    final_top_bid, final_top_ask, final_spread.

    NOTE: resolution-watcher is not yet built, so this currently returns an
    empty DataFrame with the target schema.
    """

    del con, since
    return pd.DataFrame(
        columns=[
            "venue",
            "market_id",
            "resolution_timestamp",
            "resolved_value",
            "final_top_bid",
            "final_top_ask",
            "final_spread",
        ]
    )


def _create_forward_index_views(con: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    _create_view(
        con,
        "order_book_snapshots",
        data_dir,
        """
        SELECT
            CAST(NULL AS SMALLINT) AS schema_version,
            CAST(NULL AS VARCHAR) AS venue,
            CAST(NULL AS VARCHAR) AS market_id,
            CAST(NULL AS VARCHAR) AS token_id_yes,
            CAST(NULL AS VARCHAR) AS token_id_no,
            CAST(NULL AS TIMESTAMPTZ) AS timestamp_utc,
            CAST([] AS STRUCT(price DOUBLE, size DOUBLE)[]) AS bid_levels,
            CAST([] AS STRUCT(price DOUBLE, size DOUBLE)[]) AS ask_levels,
            CAST(NULL AS DOUBLE) AS top_bid,
            CAST(NULL AS DOUBLE) AS top_ask,
            CAST(NULL AS DOUBLE) AS mid,
            CAST(NULL AS DOUBLE) AS spread,
            CAST(NULL AS VARCHAR) AS snapshot_source
        WHERE false
        """,
    )
    _create_view(
        con,
        "trade_events",
        data_dir,
        """
        SELECT
            CAST(NULL AS SMALLINT) AS schema_version,
            CAST(NULL AS VARCHAR) AS venue,
            CAST(NULL AS VARCHAR) AS market_id,
            CAST(NULL AS VARCHAR) AS token_id,
            CAST(NULL AS TIMESTAMPTZ) AS timestamp_utc,
            CAST(NULL AS DOUBLE) AS price,
            CAST(NULL AS DOUBLE) AS size,
            CAST(NULL AS VARCHAR) AS side,
            CAST(NULL AS VARCHAR) AS trade_id_venue
        WHERE false
        """,
    )
    _create_view(
        con,
        "market_metadata_snapshots",
        data_dir,
        """
        SELECT
            CAST(NULL AS SMALLINT) AS schema_version,
            CAST(NULL AS VARCHAR) AS venue,
            CAST(NULL AS VARCHAR) AS market_id,
            CAST(NULL AS TIMESTAMPTZ) AS captured_at_utc,
            CAST(NULL AS VARCHAR) AS status,
            CAST(NULL AS DOUBLE) AS volume_24h,
            CAST(NULL AS DOUBLE) AS liquidity,
            CAST(NULL AS TIMESTAMPTZ) AS end_date,
            CAST(NULL AS VARCHAR) AS raw_json
        WHERE false
        """,
    )


def _create_view(
    con: duckdb.DuckDBPyConnection,
    table: str,
    data_dir: Path,
    empty_sql: str,
) -> None:
    table_dir = data_dir / table
    if table_dir.exists() and any(table_dir.rglob("*.parquet")):
        glob = _sql_string(str(table_dir / "**" / "*.parquet"))
        con.execute(f"CREATE OR REPLACE TEMP VIEW {table} AS SELECT * FROM read_parquet({glob})")
        return
    warnings.warn(
        f"No parquet files for {table} at {table_dir}; using empty view with target schema.",
        stacklevel=2,
    )
    con.execute(f"CREATE OR REPLACE TEMP VIEW {table} AS {empty_sql}")


def _resolve_data_dir(data_dir: Path | None) -> tuple[Path, str]:
    if data_dir is not None:
        return data_dir.expanduser(), "explicit arg"
    env_value = os.environ.get(DATA_DIR_ENV)
    if env_value:
        return Path(env_value).expanduser(), f"env var {DATA_DIR_ENV}"
    return DEFAULT_DATA_DIR, "default"


def _validate_data_dir(data_dir: Path, source: str) -> None:
    expected = ", ".join(EXPECTED_TABLES)
    hint = f"set {DATA_DIR_ENV} or pass data_dir= explicitly"
    if not data_dir.is_dir():
        raise FileNotFoundError(
            f"Forward-index data_dir={data_dir} resolved from {source} does not exist "
            f"or is not a directory; {hint}. Expected subdirectories: {expected}."
        )
    if not any(
        (data_dir / table).exists() and any((data_dir / table).rglob("*.parquet"))
        for table in EXPECTED_TABLES
    ):
        raise FileNotFoundError(
            f"No parquet files found under data_dir={data_dir} resolved from {source}; "
            f"{hint}. Expected subdirectories: {expected}."
        )


def _time_filters(
    timestamp_column: str,
    *,
    venue: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[str, list[object]]:
    clauses = [f"{timestamp_column} IS NOT NULL"]
    params: list[object] = []
    if venue is not None:
        clauses.append("venue = ?")
        params.append(venue)
    if since is not None:
        clauses.append(f"{timestamp_column} >= ?")
        params.append(since)
    if until is not None:
        clauses.append(f"{timestamp_column} < ?")
        params.append(until)
    return " AND ".join(clauses), params


def _validate_timescale(timescale: str) -> None:
    if not TIMESCALE_RE.match(timescale):
        raise ValueError(f"Unsupported timescale: {timescale}")


def _fetch_df(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[object] | None = None,
) -> pd.DataFrame:
    return con.execute(sql, params or []).fetchdf()


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
