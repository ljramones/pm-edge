from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from notebooks.lib import queries


def test_get_connection_raises_when_data_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(FileNotFoundError, match="Expected subdirectories") as exc:
        queries.get_connection(missing)

    assert str(missing) in str(exc.value)


def test_get_connection_raises_when_data_dir_has_no_parquet(tmp_path: Path) -> None:
    for table in queries.EXPECTED_TABLES:
        (tmp_path / table).mkdir()

    with pytest.raises(FileNotFoundError, match="No parquet files found") as exc:
        queries.get_connection(tmp_path)

    assert "order_book_snapshots" in str(exc.value)


def test_get_connection_uses_env_data_dir(monkeypatch: Any, tmp_path: Path) -> None:
    data_dir = write_forward_index_fixture(tmp_path)
    monkeypatch.setenv(queries.DATA_DIR_ENV, str(data_dir))

    con = queries.get_connection()
    result = con.execute("SELECT count(*) FROM order_book_snapshots").fetchone()

    assert result is not None
    assert result[0] == 5


def test_get_connection_explicit_arg_wins_over_env(monkeypatch: Any, tmp_path: Path) -> None:
    env_dir = write_snapshot_only_fixture(tmp_path / "env")
    explicit_dir = write_forward_index_fixture(tmp_path / "explicit")
    monkeypatch.setenv(queries.DATA_DIR_ENV, str(env_dir))

    con = queries.get_connection(explicit_dir)
    result = con.execute("SELECT count(*) FROM order_book_snapshots").fetchone()

    assert result is not None
    assert result[0] == 5


def test_get_connection_warns_for_missing_specific_table(tmp_path: Path) -> None:
    data_dir = write_snapshot_only_fixture(tmp_path)

    with pytest.warns(UserWarning) as warnings:
        con = queries.get_connection(data_dir)

    assert any("No parquet files for trade_events" in str(warning.message) for warning in warnings)
    assert con.execute("SELECT count(*) FROM order_book_snapshots").fetchone() == (1,)
    assert con.execute("SELECT count(*) FROM trade_events").fetchone() == (0,)


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


def test_capture_freshness(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))
    now = datetime(2026, 5, 15, 2, 5, tzinfo=UTC)

    df = queries.capture_freshness(con, now=now, expected_cadence_seconds=15)

    assert {"latest_snapshot_utc", "snapshot_age_minutes", "pct_expected_snapshots"}.issubset(
        df.columns
    )
    assert set(df["venue"]) == {"polymarket", "kalshi"}
    assert df[df["venue"] == "polymarket"].iloc[0]["snapshot_age_minutes"] == 60.0


def test_snapshot_gaps_includes_missing_buckets(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.snapshot_gaps(con, venue="polymarket", bucket="20 minutes")

    assert {"venue", "bucket", "snapshot_count", "venue_median", "threshold_count"}.issubset(
        df.columns
    )
    assert 0 in set(df["snapshot_count"])


def test_book_validity(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.book_validity(con)

    assert {"pct_crossed_books", "pct_invalid_price_rows", "pct_with_top_both"}.issubset(df.columns)
    assert df["pct_crossed_books"].sum() == 0.0
    assert df["pct_with_top_both"].min() == 1.0


def test_spread_depth_summary(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.spread_depth_summary(con)

    assert {"spread_p50", "spread_p90", "avg_bid_depth", "avg_ask_depth"}.issubset(df.columns)
    assert df["avg_bid_depth"].min() == 10.0
    assert df["avg_ask_depth"].min() == 8.0


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


def test_trade_overview(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.trade_overview(con)

    assert {"trades", "markets_with_trades", "notional", "duplicate_trade_ids"}.issubset(df.columns)
    assert int(df["trades"].sum()) == 3
    assert int(df["duplicate_trade_ids"].sum()) == 0


def test_metadata_universe(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.metadata_universe(con)

    assert {"metadata_rows", "markets", "volume_24h_p50", "avg_hours_to_close"}.issubset(df.columns)
    assert int(df.iloc[0]["markets"]) == 1
    assert df.iloc[0]["avg_hours_to_close"] == 24.0


def test_data_integrity_checks(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.data_integrity_checks(con)

    assert {"table_name", "check_name", "issue_count"}.issubset(df.columns)
    duplicate_snapshots = df[df["check_name"] == "duplicate_snapshot_keys"].iloc[0]
    assert int(duplicate_snapshots["issue_count"]) == 0


def test_analysis_readiness(tmp_path: Path) -> None:
    con = queries.get_connection(write_forward_index_fixture(tmp_path))

    df = queries.analysis_readiness(con, min_snapshots=2, min_distinct_top_bids=2)

    ready = df[df["is_analysis_ready"]]
    not_ready = df[~df["is_analysis_ready"]]
    assert set(ready["market_id"]) == {"poly-1", "kalshi-1"}
    assert "low_snapshots" in set(not_ready["exclusion_reason"])


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


@pytest.mark.parametrize(
    ("raw_json", "expected"),
    [
        ({"feeType": "sports_fees_v2", "question": "Will Iran strike Israel?"}, "sports"),
        ({"feeType": "politics_fees", "question": "Will Russia and Ukraine agree?"}, "politics"),
        ({"feeType": "crypto_prices", "question": "Will Bitcoin hit 120k?"}, "crypto"),
        ({"feeType": "culture", "question": "Will a film win best picture?"}, "culture"),
        ({"feeType": "finance", "question": "Will CPI be above forecast?"}, "finance"),
        ({"question": "Will Iran announce a nuclear agreement?"}, "geopolitics"),
        ({"slug": "russia-ukraine-ceasefire-before-june"}, "geopolitics"),
        (
            {"groupItemTitle": "Middle East tensions", "question": "Will there be an airstrike?"},
            "geopolitics",
        ),
        ({"question": "Will the movie win an award?"}, "polymarket_uncategorized"),
    ],
)
def test_polymarket_category_expression(raw_json: dict[str, str], expected: str) -> None:
    con = duckdb.connect()
    expression = queries.polymarket_category_expression("raw_json")

    result = con.execute(
        f"SELECT {expression} AS category FROM (SELECT ? AS raw_json)",
        [json.dumps(raw_json)],
    ).fetchone()

    assert result == (expected,)


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
    write_table(
        data_dir
        / "market_metadata_snapshots"
        / "venue=polymarket"
        / "date=2026-05-15"
        / "part.parquet",
        [metadata_row("polymarket", "poly-1", base)],
        market_metadata_snapshot_schema(),
    )
    return data_dir


def write_snapshot_only_fixture(tmp_path: Path) -> Path:
    data_dir = tmp_path / "forward_index"
    row = snapshot_row(
        "polymarket", "poly-1", datetime(2026, 5, 15, tzinfo=UTC), 0.49, 0.51, "rest"
    )
    write_table(
        data_dir / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-15" / "part.parquet",
        [row],
        order_book_snapshot_schema(),
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


def market_metadata_snapshot_schema() -> pa.Schema:
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


def metadata_row(venue: str, market_id: str, timestamp: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "venue": venue,
        "market_id": market_id,
        "captured_at_utc": timestamp,
        "status": "open",
        "volume_24h": 10_000.0,
        "liquidity": 1_000.0,
        "end_date": timestamp + timedelta(days=1),
        "raw_json": "{}",
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
