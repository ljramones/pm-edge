"""Versioned pyarrow schemas for forward-indexed venue data."""

from __future__ import annotations

from enum import StrEnum

import pyarrow as pa

SCHEMA_VERSION = 1


class TableName(StrEnum):
    """Forward-indexer parquet table names."""

    ORDER_BOOK_SNAPSHOTS = "order_book_snapshots"
    TRADE_EVENTS = "trade_events"
    MARKET_METADATA_SNAPSHOTS = "market_metadata_snapshots"


LEVEL_TYPE = pa.list_(pa.struct([("price", pa.float64()), ("size", pa.float64())]))


def order_book_snapshot_schema() -> pa.Schema:
    """Return the order-book snapshot parquet schema."""

    return pa.schema(
        [
            ("schema_version", pa.int16()),
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("token_id_yes", pa.string()),
            ("token_id_no", pa.string()),
            ("timestamp_utc", pa.timestamp("us", tz="UTC")),
            ("bid_levels", LEVEL_TYPE),
            ("ask_levels", LEVEL_TYPE),
            ("top_bid", pa.float64()),
            ("top_ask", pa.float64()),
            ("mid", pa.float64()),
            ("spread", pa.float64()),
            ("snapshot_source", pa.string()),
        ]
    )


def trade_event_schema() -> pa.Schema:
    """Return the trade-event parquet schema."""

    return pa.schema(
        [
            ("schema_version", pa.int16()),
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("token_id", pa.string()),
            ("timestamp_utc", pa.timestamp("us", tz="UTC")),
            ("price", pa.float64()),
            ("size", pa.float64()),
            ("side", pa.string()),
            ("trade_id_venue", pa.string()),
        ]
    )


def market_metadata_snapshot_schema() -> pa.Schema:
    """Return the market-metadata snapshot parquet schema."""

    return pa.schema(
        [
            ("schema_version", pa.int16()),
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("captured_at_utc", pa.timestamp("us", tz="UTC")),
            ("status", pa.string()),
            ("volume_24h", pa.float64()),
            ("liquidity", pa.float64()),
            ("end_date", pa.timestamp("us", tz="UTC")),
            ("raw_json", pa.string()),
        ]
    )


def schema_for_table(table_name: str | TableName) -> pa.Schema:
    """Return the pyarrow schema for a forward-indexer table."""

    table = TableName(table_name)
    if table is TableName.ORDER_BOOK_SNAPSHOTS:
        return order_book_snapshot_schema()
    if table is TableName.TRADE_EVENTS:
        return trade_event_schema()
    if table is TableName.MARKET_METADATA_SNAPSHOTS:
        return market_metadata_snapshot_schema()
    raise ValueError(f"Unsupported table: {table_name}")
