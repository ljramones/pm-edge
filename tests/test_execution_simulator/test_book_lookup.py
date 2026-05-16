from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from execution_simulator.book_lookup import BookLookup


def test_book_lookup_returns_latest_snapshot_before_submission(
    archive_path: Path,
    base_time: datetime,
) -> None:
    lookup = BookLookup(archive_path)
    try:
        snapshot = lookup.get_snapshot(
            venue="polymarket",
            market_id="market-1",
            submitted_at=base_time + timedelta(minutes=1, seconds=30),
        )
    finally:
        lookup.close()

    assert snapshot is not None
    assert snapshot.timestamp_utc == base_time + timedelta(minutes=1)
    assert snapshot.top_bid == 0.50
    assert snapshot.top_ask == 0.52
    assert snapshot.ask_levels == [{"price": 0.52, "size": 8.0}]


def test_book_lookup_returns_none_when_no_prior_snapshot(
    archive_path: Path,
    base_time: datetime,
) -> None:
    lookup = BookLookup(archive_path)
    try:
        snapshot = lookup.get_snapshot(
            venue="polymarket",
            market_id="market-1",
            submitted_at=base_time - timedelta(seconds=1),
        )
    finally:
        lookup.close()

    assert snapshot is None


def test_book_lookup_raises_when_snapshot_table_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="order_book_snapshots"):
        BookLookup(tmp_path / "forward_index")


def test_book_snapshot_age_uses_utc_datetimes(archive_path: Path) -> None:
    lookup = BookLookup(archive_path)
    try:
        snapshot = lookup.get_snapshot(
            venue="polymarket",
            market_id="market-1",
            submitted_at=datetime(2026, 5, 15, 12, 0, 30, tzinfo=UTC),
        )
    finally:
        lookup.close()

    assert snapshot is not None
    assert snapshot.age_at(datetime(2026, 5, 15, 12, 0, 30, tzinfo=UTC)) == 30.0
