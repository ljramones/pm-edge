from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 5, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def source_archive(tmp_path: Path, base_time: datetime) -> Path:
    archive = tmp_path / "forward_index"
    write_table(
        archive
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-16"
        / "part.parquet",
        [
            metadata_row(
                "polymarket",
                "poly-1",
                base_time,
                base_time - timedelta(hours=1),
                "closed",
                {"closed": True, "conditionId": "poly-1"},
            )
        ],
        metadata_schema(),
    )
    write_table(
        archive / "market_metadata_snapshots" / "venue=kalshi" / "date=2026-05-16" / "part.parquet",
        [
            metadata_row(
                "kalshi",
                "KTEST-YES",
                base_time,
                base_time - timedelta(hours=1),
                "settled",
                {"status": "settled"},
            )
        ],
        metadata_schema(),
    )
    write_table(
        archive / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-16" / "part.parquet",
        [snapshot_row("polymarket", "poly-1", base_time - timedelta(minutes=10))],
        snapshot_schema(),
    )
    write_table(
        archive / "order_book_snapshots" / "venue=kalshi" / "date=2026-05-16" / "part.parquet",
        [snapshot_row("kalshi", "KTEST-YES", base_time - timedelta(minutes=10))],
        snapshot_schema(),
    )
    return archive


def write_table(path: Path, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def metadata_schema() -> pa.Schema:
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


def snapshot_schema() -> pa.Schema:
    level_type = pa.list_(pa.struct([("price", pa.float64()), ("size", pa.float64())]))
    return pa.schema(
        [
            ("schema_version", pa.int16()),
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("token_id_yes", pa.string()),
            ("token_id_no", pa.string()),
            ("timestamp_utc", pa.timestamp("us", tz="UTC")),
            ("bid_levels", level_type),
            ("ask_levels", level_type),
            ("top_bid", pa.float64()),
            ("top_ask", pa.float64()),
            ("mid", pa.float64()),
            ("spread", pa.float64()),
            ("snapshot_source", pa.string()),
        ]
    )


def metadata_row(
    venue: str,
    market_id: str,
    captured_at: datetime,
    end_date: datetime,
    status: str,
    raw_json: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "venue": venue,
        "market_id": market_id,
        "captured_at_utc": captured_at,
        "status": status,
        "volume_24h": 1_000.0,
        "liquidity": 100.0,
        "end_date": end_date,
        "raw_json": json.dumps(raw_json),
    }


def snapshot_row(venue: str, market_id: str, timestamp: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "venue": venue,
        "market_id": market_id,
        "token_id_yes": f"{market_id}-yes",
        "token_id_no": f"{market_id}-no",
        "timestamp_utc": timestamp,
        "bid_levels": [{"price": 0.40, "size": 10.0}],
        "ask_levels": [{"price": 0.60, "size": 10.0}],
        "top_bid": 0.40,
        "top_ask": 0.60,
        "mid": 0.50,
        "spread": 0.20,
        "snapshot_source": "rest",
    }
