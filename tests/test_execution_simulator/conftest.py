from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def archive_path(tmp_path: Path) -> Path:
    return write_archive_fixture(tmp_path)


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


def write_archive_fixture(tmp_path: Path) -> Path:
    data_dir = tmp_path / "forward_index"
    base = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    snapshots = [
        snapshot_row("polymarket", "market-1", base, 0.49, 0.51, "websocket"),
        snapshot_row(
            "polymarket",
            "market-1",
            base + timedelta(minutes=1),
            0.50,
            0.52,
            "websocket",
        ),
        snapshot_row("kalshi", "market-2", base, 0.10, 0.12, "rest"),
        snapshot_row("polymarket", "empty-ask", base, 0.49, None, "rest"),
    ]
    trades = [
        trade_row("polymarket", "market-1", base + timedelta(seconds=30), 0.51, 2.0, "buy"),
        trade_row("polymarket", "market-1", base + timedelta(seconds=45), 0.51, 12.0, "buy"),
        trade_row("kalshi", "market-2", base + timedelta(seconds=30), 0.10, 1.0, "sell"),
    ]

    for index, row in enumerate(snapshots):
        write_table(
            data_dir
            / "order_book_snapshots"
            / f"venue={row['venue']}"
            / "date=2026-05-15"
            / f"part-{index}.parquet",
            [row],
            order_book_snapshot_schema(),
        )
    write_table(
        data_dir / "trade_events" / "venue=polymarket" / "date=2026-05-15" / "part.parquet",
        [row for row in trades if row["venue"] == "polymarket"],
        trade_event_schema(),
    )
    write_table(
        data_dir / "trade_events" / "venue=kalshi" / "date=2026-05-15" / "part.parquet",
        [row for row in trades if row["venue"] == "kalshi"],
        trade_event_schema(),
    )
    return data_dir


def write_table(path: Path, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def order_book_snapshot_schema() -> pa.Schema:
    return pa.schema(
        [
            ("schema_version", pa.int16()),
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("token_id_yes", pa.string()),
            ("token_id_no", pa.string()),
            ("timestamp_utc", pa.timestamp("us", tz="UTC")),
            ("bid_levels", pa.list_(pa.struct([("price", pa.float64()), ("size", pa.float64())]))),
            ("ask_levels", pa.list_(pa.struct([("price", pa.float64()), ("size", pa.float64())]))),
            ("top_bid", pa.float64()),
            ("top_ask", pa.float64()),
            ("mid", pa.float64()),
            ("spread", pa.float64()),
            ("snapshot_source", pa.string()),
        ]
    )


def trade_event_schema() -> pa.Schema:
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


def snapshot_row(
    venue: str,
    market_id: str,
    timestamp: datetime,
    bid: float | None,
    ask: float | None,
    source: str,
) -> dict[str, Any]:
    bid_levels = [] if bid is None else [{"price": bid, "size": 10.0}]
    ask_levels = [] if ask is None else [{"price": ask, "size": 8.0}]
    mid = None if bid is None or ask is None else round((bid + ask) / 2, 4)
    spread = None if bid is None or ask is None else round(ask - bid, 4)
    return {
        "schema_version": 1,
        "venue": venue,
        "market_id": market_id,
        "token_id_yes": f"{market_id}-yes",
        "token_id_no": f"{market_id}-no",
        "timestamp_utc": timestamp,
        "bid_levels": bid_levels,
        "ask_levels": ask_levels,
        "top_bid": bid,
        "top_ask": ask,
        "mid": mid,
        "spread": spread,
        "snapshot_source": source,
    }


def trade_row(
    venue: str,
    market_id: str,
    timestamp: datetime,
    price: float,
    size: float,
    side: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "venue": venue,
        "market_id": market_id,
        "token_id": f"{market_id}-yes",
        "timestamp_utc": timestamp,
        "price": price,
        "size": size,
        "side": side,
        "trade_id_venue": f"{market_id}-{int(timestamp.timestamp())}-{side}",
    }
