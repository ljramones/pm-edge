from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from notebooks.lib import queries


def test_get_connection_uses_env_data_dir(monkeypatch: Any, tmp_path: Path) -> None:
    data_dir = write_forward_index_fixture(tmp_path)
    monkeypatch.setenv(queries.DATA_DIR_ENV, str(data_dir))

    con = queries.get_connection()
    result = con.execute("SELECT count(*) FROM order_book_snapshots").fetchone()

    assert result is not None
    assert result[0] == 5


def test_hourly_snapshot_volume(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.hourly_snapshot_volume(con)

    assert set(df.columns) == {"venue", "hour", "snapshots", "distinct_markets"}
    assert int(df["snapshots"].sum()) == 5
    assert set(df["venue"]) == {"polymarket", "kalshi"}


def test_source_breakdown(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.source_breakdown(con)

    assert set(df.columns) == {"venue", "snapshot_source", "count", "pct_of_venue"}
    poly = df[df["venue"] == "polymarket"]
    assert set(poly["snapshot_source"]) == {"rest", "websocket"}


def test_book_state_quality(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.book_state_quality(con, venue="kalshi")

    assert int(df.iloc[0]["snapshots"]) == 2
    assert df.iloc[0]["avg_bid_levels"] == 1.0
    assert df.iloc[0]["pct_with_top_bid"] == 1.0


def test_market_movement(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.market_movement(con, venue="polymarket")

    assert {"spread_min", "spread_max", "price_min", "price_max"}.issubset(df.columns)
    p1 = df[df["market_id"] == "poly-1"].iloc[0]
    assert int(p1["distinct_top_bids"]) == 2
    assert p1["price_min"] == 0.50
    assert p1["price_max"] == 0.53


def test_trade_volume_by_hour(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.trade_volume(con, groupby="hour")

    assert {"venue", "hour", "trades", "contracts", "notional"}.issubset(df.columns)
    assert int(df["trades"].sum()) == 3


def test_trade_volume_by_market(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.trade_volume(con, groupby="market")

    assert {"venue", "market_id", "trades", "contracts", "notional"}.issubset(df.columns)
    assert set(df["market_id"]) == {"poly-1", "kalshi-1"}


def test_multi_timescale_aggregation(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    aggs = queries.multi_timescale_aggregation(con, "poly-1", ["1 hour", "1 day"])

    assert set(aggs) == {"1 hour", "1 day"}
    assert {"bucket", "mid_open", "mid_close", "mid", "snapshots"}.issubset(aggs["1 hour"].columns)
    assert int(aggs["1 hour"]["snapshots"].sum()) == 2


def test_resolved_market_outcomes_stub(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.resolved_market_outcomes(con)

    assert df.empty
    assert list(df.columns) == [
        "venue",
        "market_id",
        "resolution_timestamp",
        "resolved_value",
        "final_top_bid",
        "final_top_ask",
        "final_spread",
    ]


def test_missing_archive_returns_empty_dataframes(tmp_path: Path) -> None:
    con = queries.get_connection(tmp_path / "missing")

    assert queries.hourly_snapshot_volume(con).empty
    assert queries.source_breakdown(con).empty
    assert int(queries.book_state_quality(con, venue="polymarket").iloc[0]["snapshots"]) == 0


def write_forward_index_fixture(tmp_path: Path) -> Path:
    data_dir = tmp_path / "forward_index"
    base = datetime(2026, 5, 15, 0, 5, tzinfo=UTC)
    snapshots = [
        snapshot_row("polymarket", "poly-1", base, 0.49, 0.51, "rest"),
        snapshot_row("polymarket", "poly-1", base + timedelta(minutes=20), 0.52, 0.54, "websocket"),
        snapshot_row("polymarket", "poly-2", base + timedelta(hours=1), 0.20, 0.28, "websocket"),
        snapshot_row("kalshi", "kalshi-1", base + timedelta(minutes=10), 0.10, 0.12, "rest"),
        snapshot_row("kalshi", "kalshi-1", base + timedelta(hours=1), 0.11, 0.14, "rest"),
    ]
    trades = [
        trade_row("polymarket", "poly-1", base + timedelta(minutes=2), 0.50, 10.0, "t1"),
        trade_row("polymarket", "poly-1", base + timedelta(minutes=30), 0.53, 5.0, "t2"),
        trade_row("kalshi", "kalshi-1", base + timedelta(minutes=20), 0.11, 20.0, "t3"),
    ]
    for idx, row in enumerate(snapshots):
        write_table(
            data_dir
            / "order_book_snapshots"
            / f"venue={row['venue']}"
            / "date=2026-05-15"
            / f"part-{idx}.parquet",
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
    bid: float,
    ask: float,
    source: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "venue": venue,
        "market_id": market_id,
        "token_id_yes": f"{market_id}-yes",
        "token_id_no": f"{market_id}-no",
        "timestamp_utc": timestamp,
        "bid_levels": [{"price": bid, "size": 10.0}],
        "ask_levels": [{"price": ask, "size": 8.0}],
        "top_bid": bid,
        "top_ask": ask,
        "mid": round((bid + ask) / 2, 4),
        "spread": round(ask - bid, 4),
        "snapshot_source": source,
    }


def trade_row(
    venue: str,
    market_id: str,
    timestamp: datetime,
    price: float,
    size: float,
    trade_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "venue": venue,
        "market_id": market_id,
        "token_id": f"{market_id}-yes",
        "timestamp_utc": timestamp,
        "price": price,
        "size": size,
        "side": "buy",
        "trade_id_venue": trade_id,
    }
