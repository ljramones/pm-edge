"""Tests for the Experiment 2 hi-cad capture-rate measurement script."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.experiment_02_capture_rate import (
    HICAD_SOURCE,
    infer_days_elapsed,
    load_capture_stats,
    project,
)

_BASE = datetime(2026, 5, 25, 18, 0, 0, tzinfo=UTC)


def _ob_schema() -> pa.Schema:
    return pa.schema(
        [
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("timestamp_utc", pa.timestamp("us", tz="UTC")),
            ("snapshot_source", pa.string()),
        ]
    )


def _resolved_schema() -> pa.Schema:
    return pa.schema(
        [
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("resolution_timestamp_utc", pa.timestamp("us", tz="UTC")),
            ("resolved_value", pa.float64()),
        ]
    )


def _write(path: Path, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def _snap(market_id: str, offset_s: int, source: str = HICAD_SOURCE) -> dict[str, Any]:
    return {
        "venue": "kalshi",
        "market_id": market_id,
        "timestamp_utc": _BASE + timedelta(seconds=offset_s),
        "snapshot_source": source,
    }


def _resolved(market_id: str, value: float) -> dict[str, Any]:
    return {
        "venue": "kalshi",
        "market_id": market_id,
        "resolution_timestamp_utc": _BASE + timedelta(hours=1),
        "resolved_value": value,
    }


def _globs(tmp_path: Path, venue: str = "kalshi") -> tuple[str, str]:
    hicad = tmp_path / "forward_index" / "order_book_snapshots" / f"venue={venue}"
    resolved = tmp_path / "resolved_market_outcomes" / f"venue={venue}"
    return (
        str(hicad / "**" / "*.parquet"),
        str(resolved / "**" / "*.parquet"),
    )


def _ob_dir(tmp_path: Path, venue: str = "kalshi") -> Path:
    return (
        tmp_path / "forward_index" / "order_book_snapshots" / f"venue={venue}" / "date=2026-05-25"
    )


def _res_dir(tmp_path: Path, venue: str = "kalshi") -> Path:
    return tmp_path / "resolved_market_outcomes" / f"venue={venue}" / "date=2026-05-25"


# --------------------------------------------------------------------------- #
# Test 1: correct usable-event count
# --------------------------------------------------------------------------- #
def test_usable_event_count(tmp_path: Path) -> None:
    snaps = (
        [_snap("m1", s) for s in (0, 150, 300, 450, 600)]  # 5 hi-cad, span 600s
        + [_snap("m2", s) for s in (0, 120, 240)]  # 3 hi-cad
        + [_snap("m3", s) for s in (0, 60)]  # 2 hi-cad, NOT resolved
        + [_snap("m1", 30, source="websocket")]  # normal snap, must be ignored
    )
    _write(_ob_dir(tmp_path) / "part.parquet", snaps, _ob_schema())
    _write(
        _res_dir(tmp_path) / "part.parquet",
        [
            _resolved("m1", 1.0),
            _resolved("m2", 0.0),
            _resolved("m_other", 1.0),  # resolved but no hi-cad — must not appear
            _resolved("m_frac", 0.5),  # not 0/1 — must not count as usable
        ],
        _resolved_schema(),
    )

    hicad_glob, resolved_glob = _globs(tmp_path)
    stats = load_capture_stats(hicad_glob, resolved_glob)

    assert stats.total_snapshots == 10  # websocket snap excluded
    assert stats.distinct_markets == 3
    assert stats.usable_event_count == 2  # m1, m2 (m3 unresolved)
    assert stats.unresolved_count == 1  # m3
    m1 = stats.per_market[stats.per_market["market_id"] == "m1"].iloc[0]
    assert int(m1["hicad_snapshots"]) == 5
    assert int(m1["span_seconds"]) == 600


# --------------------------------------------------------------------------- #
# Test 2: hi-cad with no matching resolution → captured-but-unresolved
# --------------------------------------------------------------------------- #
def test_unresolved_hicad_not_counted_as_usable(tmp_path: Path) -> None:
    _write(_ob_dir(tmp_path) / "part.parquet", [_snap("m4", 0), _snap("m4", 60)], _ob_schema())
    # resolved set exists but contains a different market.
    _write(_res_dir(tmp_path) / "part.parquet", [_resolved("other", 1.0)], _resolved_schema())

    hicad_glob, resolved_glob = _globs(tmp_path)
    stats = load_capture_stats(hicad_glob, resolved_glob)

    assert stats.distinct_markets == 1
    assert stats.usable_event_count == 0
    assert stats.unresolved_count == 1


# --------------------------------------------------------------------------- #
# Test 3: projection math
# --------------------------------------------------------------------------- #
def test_projection_math() -> None:
    rate, days = project(30, 2, 150)
    assert rate == 15.0
    assert days == 8.0  # (150 - 30) / 15

    rate, days = project(0, 5, 150)
    assert rate == 0.0
    assert days is None  # cannot project at zero rate

    rate, days = project(200, 10, 150)
    assert rate == 20.0
    assert days == 0.0  # target already exceeded


def test_infer_days_elapsed() -> None:
    today = date(2026, 5, 27)
    assert infer_days_elapsed(None, today) == 0
    assert infer_days_elapsed(date(2026, 5, 27), today) == 1  # same day -> 1
    assert infer_days_elapsed(date(2026, 5, 25), today) == 3  # inclusive


# --------------------------------------------------------------------------- #
# Test 4: zero hi-cad snapshots → reports 0 cleanly, no crash / no div-by-zero
# --------------------------------------------------------------------------- #
def test_zero_hicad_snapshots(tmp_path: Path) -> None:
    # Order-book files exist, but none are tagged hi-cad.
    _write(
        _ob_dir(tmp_path) / "part.parquet",
        [_snap("m1", 0, source="websocket"), _snap("m1", 60, source="rest")],
        _ob_schema(),
    )
    _write(_res_dir(tmp_path) / "part.parquet", [_resolved("m1", 1.0)], _resolved_schema())

    hicad_glob, resolved_glob = _globs(tmp_path)
    stats = load_capture_stats(hicad_glob, resolved_glob)

    assert stats.total_snapshots == 0
    assert stats.distinct_markets == 0
    assert stats.usable_event_count == 0
    assert stats.earliest_day is None

    days = infer_days_elapsed(stats.earliest_day, date(2026, 5, 27))
    rate, days_to_target = project(stats.usable_event_count, days, 150)
    assert rate == 0.0
    assert days_to_target is None


def test_format_summary_runs_for_empty_and_populated(tmp_path: Path) -> None:
    from scripts.experiment_02_capture_rate import format_summary

    # Populated
    _write(_ob_dir(tmp_path) / "p.parquet", [_snap("m1", 0), _snap("m1", 300)], _ob_schema())
    _write(_res_dir(tmp_path) / "p.parquet", [_resolved("m1", 1.0)], _resolved_schema())
    hicad_glob, resolved_glob = _globs(tmp_path)
    stats = load_capture_stats(hicad_glob, resolved_glob)
    text = format_summary(stats, days_elapsed=2, target=150, venue="kalshi")
    assert "PROJECTION" in text
    assert "usable events so far   : 1" in text

    # Empty (no usable events) must still render without error — build a no-hicad archive.
    other = tmp_path / "empty_arch"
    _write(
        other
        / "forward_index"
        / "order_book_snapshots"
        / "venue=kalshi"
        / "date=2026-05-25"
        / "p.parquet",
        [_snap("x", 0, source="rest")],
        _ob_schema(),
    )
    _write(
        other / "resolved_market_outcomes" / "venue=kalshi" / "date=2026-05-25" / "p.parquet",
        [_resolved("x", 1.0)],
        _resolved_schema(),
    )
    empty = load_capture_stats(*_globs(other))
    empty_text = format_summary(empty, days_elapsed=0, target=150, venue="kalshi")
    assert "rate is 0" in empty_text


def test_require_parquet_raises_on_missing(tmp_path: Path) -> None:
    from scripts.experiment_02_capture_rate import main

    with pytest.raises((FileNotFoundError, SystemExit)):
        main(
            [
                "--forward-index-dir",
                str(tmp_path / "nope"),
                "--resolved-dir",
                str(tmp_path / "nope2"),
            ]
        )
