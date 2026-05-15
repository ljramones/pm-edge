from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from scripts import ops_status


def test_ops_status_runs_against_synthetic_parquet(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    now = datetime.now(tz=UTC)
    data_dir = tmp_path / "forward_index"
    output = tmp_path / "ops_status.html"
    write_snapshot_parquet(
        data_dir,
        [
            snapshot_row("polymarket", "m1", now - timedelta(minutes=2), "websocket"),
            snapshot_row("kalshi", "k1", now - timedelta(minutes=1), "rest"),
        ],
    )
    write_trade_parquet(
        data_dir,
        [
            {
                "schema_version": 1,
                "venue": "polymarket",
                "market_id": "m1",
                "token_id": "yes1",
                "timestamp_utc": now - timedelta(minutes=1),
                "price": 0.51,
                "size": 10.0,
                "side": "buy",
                "trade_id_venue": "t1",
            }
        ],
    )
    monkeypatch.setattr(ops_status, "run_command", lambda *_args, **_kwargs: None)

    result = ops_status.main(
        [
            "--data-dir",
            str(data_dir),
            "--output",
            str(output),
            "--memory-cap-mb",
            "512",
        ]
    )

    assert result == 0
    html = output.read_text(encoding="utf-8")
    assert "<!doctype html>" in html
    assert "Service health" in html
    assert "Capture rate" in html
    assert "Data quality" in html


def test_storage_growth_rate_uses_recent_file_mtimes(tmp_path: Path) -> None:
    now = datetime(2026, 5, 15, 12, tzinfo=UTC)
    recent = tmp_path / "recent.parquet"
    old = tmp_path / "old.parquet"
    recent.write_bytes(b"x" * 2_400)
    old.write_bytes(b"x" * 9_600)
    os.utime(recent, (now.timestamp() - 60, now.timestamp() - 60))
    os.utime(old, (now.timestamp() - 48 * 60 * 60, now.timestamp() - 48 * 60 * 60))

    growth = ops_status.storage_growth_mb_per_hour([recent, old], now=now)

    assert round(growth, 8) == round(2_400 / (1024 * 1024) / 24, 8)


def test_gap_detection_identifies_low_five_minute_window() -> None:
    rows = [
        {"venue": "polymarket", "bucket_ms": 1, "snapshot_count": 100},
        {"venue": "polymarket", "bucket_ms": 2, "snapshot_count": 95},
        {"venue": "polymarket", "bucket_ms": 3, "snapshot_count": 0},
        {"venue": "polymarket", "bucket_ms": 4, "snapshot_count": 105},
    ]

    gaps = ops_status.detect_snapshot_gaps(rows)

    assert gaps == [
        {
            "venue": "polymarket",
            "bucket_ms": 3,
            "snapshot_count": 0,
            "median": 97.5,
        }
    ]


def test_service_color_coding() -> None:
    assert ops_status.service_color("active", 0, 100.0, 512.0) == "green"
    assert ops_status.service_color("active", 1, 100.0, 512.0) == "yellow"
    assert ops_status.service_color("active", 0, 450.0, 512.0) == "yellow"
    assert ops_status.service_color("active", 0, 500.0, 512.0) == "red"
    assert ops_status.service_color("inactive", 0, 100.0, 512.0) == "red"


def test_missing_parquet_directory_renders_empty_sections(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    output = tmp_path / "missing.html"
    monkeypatch.setattr(ops_status, "run_command", lambda *_args, **_kwargs: None)

    assert ops_status.main(["--data-dir", str(tmp_path / "missing"), "--output", str(output)]) == 0

    html = output.read_text(encoding="utf-8")
    assert "No data available." in html
    assert "Service health" in html


def test_systemctl_error_shows_unknown_service(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    output = tmp_path / "systemctl-error.html"
    monkeypatch.setattr(ops_status, "run_command", lambda *_args, **_kwargs: None)

    assert ops_status.main(["--data-dir", str(tmp_path / "empty"), "--output", str(output)]) == 0

    html = output.read_text(encoding="utf-8")
    assert "<th>Active state</th><td>unknown</td>" in html


def write_snapshot_parquet(data_dir: Path, rows: list[dict[str, Any]]) -> None:
    schema = pa.schema(
        [
            ("schema_version", pa.int16()),
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("token_id_yes", pa.string()),
            ("token_id_no", pa.string()),
            ("timestamp_utc", pa.timestamp("us", tz="UTC")),
            (
                "bid_levels",
                pa.list_(pa.struct([("price", pa.float64()), ("size", pa.float64())])),
            ),
            (
                "ask_levels",
                pa.list_(pa.struct([("price", pa.float64()), ("size", pa.float64())])),
            ),
            ("top_bid", pa.float64()),
            ("top_ask", pa.float64()),
            ("mid", pa.float64()),
            ("spread", pa.float64()),
            ("snapshot_source", pa.string()),
        ]
    )
    for idx, row in enumerate(rows):
        path = (
            data_dir
            / "order_book_snapshots"
            / f"venue={row['venue']}"
            / f"date={row['timestamp_utc'].date().isoformat()}"
            / f"part-test-{idx}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist([row], schema=schema), path)


def write_trade_parquet(data_dir: Path, rows: list[dict[str, Any]]) -> None:
    path = (
        data_dir
        / "trade_events"
        / f"venue={rows[0]['venue']}"
        / f"date={rows[0]['timestamp_utc'].date().isoformat()}"
        / "part-test.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
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
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def snapshot_row(
    venue: str,
    market_id: str,
    timestamp: datetime,
    source: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "venue": venue,
        "market_id": market_id,
        "token_id_yes": f"{market_id}-yes",
        "token_id_no": f"{market_id}-no",
        "timestamp_utc": timestamp,
        "bid_levels": [{"price": 0.49, "size": 10.0}],
        "ask_levels": [{"price": 0.51, "size": 8.0}],
        "top_bid": 0.49,
        "top_ask": 0.51,
        "mid": 0.50,
        "spread": 0.02,
        "snapshot_source": source,
    }
