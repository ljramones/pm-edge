"""Reusable DuckDB queries for forward-indexer parquet archives."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd

DEFAULT_DATA_DIR = Path("~/pm-edge-data/forward_index").expanduser()
DATA_DIR_ENV = "PM_EDGE_LOCAL_FORWARD_INDEX_DIR"

TIMESCALE_RE = re.compile(r"^\d+\s+(minute|hour|day)s?$")


def get_connection(data_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection configured to read the local parquet archive.

    `data_dir` defaults to the PM_EDGE_LOCAL_FORWARD_INDEX_DIR environment variable,
    or ~/pm-edge-data/forward_index if not set.
    """

    root = data_dir or Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR)).expanduser()
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
    con.execute(f"CREATE OR REPLACE TEMP VIEW {table} AS {empty_sql}")


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
