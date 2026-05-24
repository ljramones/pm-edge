"""Tests for the parquet part-file compaction job."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import scripts.compact_parquet as cp
from data.forward_indexer.schemas import order_book_snapshot_schema
from scripts.compact_parquet import (
    ACTION_COMPACTED,
    ACTION_RECOVERED,
    ACTION_SKIPPED_ALREADY,
    ACTION_SKIPPED_EMPTY,
    ACTION_SKIPPED_SINGLE,
    ACTION_SKIPPED_TODAY,
    ACTION_WOULD_COMPACT,
    CompactionVerificationError,
    Partition,
    compact_partition,
    compact_root,
    discover_partitions,
)

_BASE_TS = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)


def _ob_rows(market_id: str, count: int, *, start: int = 0) -> list[dict]:
    """Build order-book snapshot rows with non-trivial STRUCT level columns."""

    rows = []
    for i in range(count):
        idx = start + i
        rows.append(
            {
                "schema_version": 1,
                "venue": "polymarket",
                "market_id": market_id,
                "token_id_yes": "yes-token",
                "token_id_no": "no-token",
                "timestamp_utc": _BASE_TS + timedelta(seconds=idx),
                "bid_levels": [
                    {"price": 0.40 + idx * 0.0001, "size": 100.0 + idx},
                    {"price": 0.39, "size": 50.0},
                ],
                "ask_levels": [
                    {"price": 0.60 - idx * 0.0001, "size": 80.0 + idx},
                ],
                "top_bid": 0.40 + idx * 0.0001,
                "top_ask": 0.60 - idx * 0.0001,
                "mid": 0.50,
                "spread": 0.20,
                "snapshot_source": "ws",
            }
        )
    return rows


def _write_part(partition_dir: Path, rows: list[dict], *, name: str) -> Path:
    partition_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=order_book_snapshot_schema())
    path = partition_dir / name
    pq.write_table(table, path)
    return path


def _make_partition(
    root: Path,
    *,
    day: str,
    venue: str = "polymarket",
    table: str = "order_book_snapshots",
) -> Partition:
    partition_dir = root / table / f"venue={venue}" / f"date={day}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    return Partition(
        path=partition_dir,
        date=date.fromisoformat(day),
        label=f"{root.name}/{table}/venue={venue}/date={day}",
    )


def _populate(partition: Partition, *, files: int, rows_per_file: int) -> int:
    total = 0
    for f in range(files):
        rows = _ob_rows("mkt-1", rows_per_file, start=f * rows_per_file)
        _write_part(partition.path, rows, name=f"part-00000{f}-aaaa{f}.parquet")
        total += rows_per_file
    return total


# --------------------------------------------------------------------------- #
# Required test 1: fewer files, identical row count
# --------------------------------------------------------------------------- #
def test_compaction_reduces_files_and_preserves_row_count(tmp_path: Path) -> None:
    partition = _make_partition(tmp_path, day="2026-05-20")
    total_rows = _populate(partition, files=5, rows_per_file=7)

    result = compact_partition(partition)

    assert result.action == ACTION_COMPACTED
    assert result.files_before == 5
    assert result.files_after < 5
    assert result.rows == total_rows

    remaining = list(partition.path.glob("*.parquet"))
    assert len(remaining) == result.files_after
    assert all(p.name.startswith(cp.COMPACT_PREFIX) for p in remaining)
    # NB: read single files via ParquetFile, not pq.read_table — the latter
    # applies hive-partition inference from the venue=/date= path and conflicts
    # with the real ``venue`` data column.
    assert sum(pq.read_metadata(p).num_rows for p in remaining) == total_rows


# --------------------------------------------------------------------------- #
# Required test 2: STRUCT columns round-trip exactly
# --------------------------------------------------------------------------- #
def test_struct_columns_round_trip(tmp_path: Path) -> None:
    partition = _make_partition(tmp_path, day="2026-05-20")
    expected_rows = _ob_rows("mkt-1", 4, start=0) + _ob_rows("mkt-1", 4, start=4)
    _write_part(partition.path, expected_rows[:4], name="part-000001-aaaa.parquet")
    _write_part(partition.path, expected_rows[4:], name="part-000002-bbbb.parquet")

    compact_partition(partition)

    files = list(partition.path.glob("*.parquet"))
    assert len(files) == 1
    compact_file = files[0]

    # Schema (including STRUCT(price DOUBLE, size DOUBLE)[]) must be identical.
    assert pq.read_schema(compact_file) == order_book_snapshot_schema()

    actual = pq.ParquetFile(str(compact_file)).read().to_pylist()
    actual.sort(key=lambda r: r["timestamp_utc"])
    expected = sorted(expected_rows, key=lambda r: r["timestamp_utc"])
    assert actual == expected
    # Spot-check the nested values explicitly.
    assert actual[0]["bid_levels"] == expected_rows[0]["bid_levels"]
    assert actual[5]["ask_levels"] == expected_rows[5]["ask_levels"]


# --------------------------------------------------------------------------- #
# Required test 3: today's partition is never touched
# --------------------------------------------------------------------------- #
def test_today_partition_is_never_touched(tmp_path: Path) -> None:
    today = date(2026, 5, 24)
    past = _make_partition(tmp_path, day="2026-05-20")
    todays = _make_partition(tmp_path, day="2026-05-24")
    future = _make_partition(tmp_path, day="2026-05-25")
    _populate(past, files=3, rows_per_file=5)
    _populate(todays, files=3, rows_per_file=5)
    _populate(future, files=3, rows_per_file=5)

    results = compact_root(tmp_path, today=today)
    by_label = {r.partition: r for r in results}

    assert by_label[past.label].action == ACTION_COMPACTED
    assert by_label[todays.label].action == ACTION_SKIPPED_TODAY
    assert by_label[future.label].action == ACTION_SKIPPED_TODAY

    # Today's and future raw files are physically untouched.
    assert len(list(todays.path.glob("part-*.parquet"))) == 3
    assert len(list(future.path.glob("part-*.parquet"))) == 3
    assert not list(todays.path.glob("compact-*.parquet"))
    # The past partition was actually compacted.
    assert len(list(past.path.glob("part-*.parquet"))) == 0
    assert len(list(past.path.glob("compact-*.parquet"))) >= 1


# --------------------------------------------------------------------------- #
# Required test 4: row-count mismatch aborts without deleting sources
# --------------------------------------------------------------------------- #
def test_row_count_mismatch_aborts_and_preserves_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partition = _make_partition(tmp_path, day="2026-05-20")
    _populate(partition, files=4, rows_per_file=6)
    sources_before = sorted(p.name for p in partition.path.glob("part-*.parquet"))

    def _dropping_writer(
        partition_dir: Path,
        source_files: list[Path],
        *,
        target_file_bytes: int,
        generation: str,
    ) -> list[Path]:
        target = pq.read_schema(source_files[0])
        tables = [pq.ParquetFile(str(f)).read().cast(target) for f in source_files]
        combined = pa.concat_tables(tables)
        truncated = combined.slice(0, combined.num_rows - 1)  # deliberately lose a row
        temp = partition_dir / f"{cp.TEMP_PREFIX}{generation}-0000.parquet"
        pq.write_table(truncated, temp)
        return [temp]

    monkeypatch.setattr(cp, "_write_compacted_files", _dropping_writer)

    with pytest.raises(CompactionVerificationError):
        compact_partition(partition)

    # Sources untouched, no compacted output, no temp leftovers.
    assert sorted(p.name for p in partition.path.glob("part-*.parquet")) == sources_before
    assert not list(partition.path.glob("compact-*.parquet"))
    assert not list(partition.path.glob(".tmp*"))


# --------------------------------------------------------------------------- #
# Required test 5: idempotent / re-runnable
# --------------------------------------------------------------------------- #
def test_compaction_is_idempotent(tmp_path: Path) -> None:
    partition = _make_partition(tmp_path, day="2026-05-20")
    _populate(partition, files=4, rows_per_file=5)

    first = compact_partition(partition)
    files_after_first = sorted(p.name for p in partition.path.glob("*.parquet"))

    second = compact_partition(partition)
    files_after_second = sorted(p.name for p in partition.path.glob("*.parquet"))

    assert first.action == ACTION_COMPACTED
    assert second.action == ACTION_SKIPPED_ALREADY
    assert files_after_first == files_after_second


# --------------------------------------------------------------------------- #
# Required test 6: empty partition handled gracefully
# --------------------------------------------------------------------------- #
def test_empty_partition_handled(tmp_path: Path) -> None:
    partition = _make_partition(tmp_path, day="2026-05-20")  # dir exists, no files
    result = compact_partition(partition)
    assert result.action == ACTION_SKIPPED_EMPTY
    assert result.files_before == 0


# --------------------------------------------------------------------------- #
# Additional behaviour
# --------------------------------------------------------------------------- #
def test_single_file_partition_skipped(tmp_path: Path) -> None:
    partition = _make_partition(tmp_path, day="2026-05-20")
    _write_part(partition.path, _ob_rows("mkt-1", 3), name="part-000001-aaaa.parquet")
    result = compact_partition(partition)
    assert result.action == ACTION_SKIPPED_SINGLE
    assert result.rows == 3
    assert len(list(partition.path.glob("*.parquet"))) == 1


def test_dry_run_makes_no_changes(tmp_path: Path) -> None:
    partition = _make_partition(tmp_path, day="2026-05-20")
    total = _populate(partition, files=4, rows_per_file=5)
    before = sorted(p.name for p in partition.path.glob("*.parquet"))

    result = compact_partition(partition, dry_run=True)

    assert result.action == ACTION_WOULD_COMPACT
    assert result.rows == total
    assert result.files_before == 4
    assert sorted(p.name for p in partition.path.glob("*.parquet")) == before


def test_crash_recovery_deletes_leftover_raw_files(tmp_path: Path) -> None:
    """A compact-* file plus leftover part-* files (crash) heals on next run."""

    partition = _make_partition(tmp_path, day="2026-05-20")
    # Simulate a completed compaction (compact-* present) that crashed before
    # deleting its sources (part-* still present, already represented in compact).
    rows = _ob_rows("mkt-1", 8)
    _write_part(partition.path, rows, name="compact-20260521T000000-deadbeef-0000.parquet")
    _write_part(partition.path, rows[:4], name="part-000001-aaaa.parquet")
    _write_part(partition.path, rows[4:], name="part-000002-bbbb.parquet")

    result = compact_partition(partition)

    assert result.action == ACTION_RECOVERED
    assert not list(partition.path.glob("part-*.parquet"))
    compacts = list(partition.path.glob("compact-*.parquet"))
    assert len(compacts) == 1
    assert pq.read_metadata(compacts[0]).num_rows == 8


def test_stale_temp_files_cleaned_before_compaction(tmp_path: Path) -> None:
    partition = _make_partition(tmp_path, day="2026-05-20")
    _populate(partition, files=3, rows_per_file=4)
    # Orphaned temp file from a previously crashed write.
    _write_part(partition.path, _ob_rows("mkt-1", 2), name=".tmp-compact-old-0000.parquet")

    compact_partition(partition)

    assert not list(partition.path.glob(".tmp*"))
    assert len(list(partition.path.glob("compact-*.parquet"))) == 1


def test_discover_partitions_forward_layout(tmp_path: Path) -> None:
    _make_partition(tmp_path, day="2026-05-20", table="order_book_snapshots")
    _make_partition(tmp_path, day="2026-05-20", table="trade_events", venue="kalshi")
    _write_part(
        tmp_path / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-20",
        _ob_rows("m", 1),
        name="part-1-a.parquet",
    )

    partitions = discover_partitions(tmp_path)
    # Two date partitions discovered (one per table), dates parsed, and the
    # date= directories themselves are not descended into.
    assert len(partitions) == 2
    assert all(p.date == date(2026, 5, 20) for p in partitions)
    assert {p.path.name for p in partitions} == {"date=2026-05-20"}


def test_discover_partitions_resolved_layout(tmp_path: Path) -> None:
    root = tmp_path / "resolved_market_outcomes"
    pdir = root / "venue=polymarket" / "date=2026-05-19"
    pdir.mkdir(parents=True)
    partitions = discover_partitions(root)
    assert len(partitions) == 1
    assert partitions[0].date == date(2026, 5, 19)
    assert partitions[0].label == "resolved_market_outcomes/venue=polymarket/date=2026-05-19"


def test_discover_partitions_missing_root(tmp_path: Path) -> None:
    assert discover_partitions(tmp_path / "nope") == []


def test_duckdb_glob_reads_compacted_archive(tmp_path: Path) -> None:
    """Mirror the production access pattern: a recursive glob count is unchanged."""

    duckdb = pytest.importorskip("duckdb")
    past = _make_partition(tmp_path, day="2026-05-20")
    todays = _make_partition(tmp_path, day="2026-05-24")
    total = _populate(past, files=6, rows_per_file=5)
    total += _populate(todays, files=2, rows_per_file=5)

    glob = str(tmp_path / "**" / "*.parquet")
    con = duckdb.connect()
    before = con.execute(f"SELECT count(*) FROM read_parquet('{glob}')").fetchone()[0]

    compact_root(tmp_path, today=date(2026, 5, 24))

    after = con.execute(f"SELECT count(*) FROM read_parquet('{glob}')").fetchone()[0]
    files_remaining = len(list((past.path).glob("*.parquet")))
    assert before == total
    assert after == total  # no rows gained or lost across the archive
    assert files_remaining < 6  # the past partition was actually compacted
