"""Point-in-time book state lookup for forward-index parquet archives."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from .types import BookSnapshot


class BookLookup:
    """Read contemporaneous book snapshots from a local parquet archive."""

    _chunk_size = 128

    def __init__(self, archive_path: Path) -> None:
        self.archive_path = archive_path.expanduser()
        self._con = duckdb.connect()
        self._validate_snapshot_archive()

    def close(self) -> None:
        self._con.close()

    def get_snapshot(
        self,
        *,
        venue: str,
        market_id: str,
        submitted_at: datetime,
    ) -> BookSnapshot | None:
        """Return the latest snapshot at or before `submitted_at`, if present."""

        submitted_utc = _ensure_utc(submitted_at)
        paths = self._snapshot_paths(venue=venue, submitted_at=submitted_utc)
        if not paths:
            return None
        submitted = submitted_utc.isoformat()
        row = self._latest_snapshot_row(
            paths=paths,
            venue=venue,
            market_id=market_id,
            submitted=submitted,
        )
        if row is None:
            return None
        return BookSnapshot(
            venue=str(row[0]),
            market_id=str(row[1]),
            timestamp_utc=_parse_duckdb_timestamp(str(row[2])),
            bid_levels=_levels(row[3]),
            ask_levels=_levels(row[4]),
            top_bid=_float_or_none(row[5]),
            top_ask=_float_or_none(row[6]),
            mid=_float_or_none(row[7]),
            spread=_float_or_none(row[8]),
            snapshot_source=str(row[9] or ""),
        )

    def _latest_snapshot_row(
        self,
        *,
        paths: list[Path],
        venue: str,
        market_id: str,
        submitted: str,
    ) -> tuple[Any, ...] | None:
        best_row: tuple[Any, ...] | None = None
        best_timestamp: datetime | None = None
        for chunk in _chunks(paths, self._chunk_size):
            parquet_paths = _parquet_list_sql(chunk)
            row = self._con.execute(
                f"""
            SELECT
                venue,
                market_id,
                timestamp_utc::VARCHAR AS timestamp_text,
                bid_levels,
                ask_levels,
                top_bid,
                top_ask,
                mid,
                spread,
                snapshot_source
            FROM read_parquet({parquet_paths})
            WHERE venue = ?
              AND market_id = ?
              AND timestamp_utc <= CAST(? AS TIMESTAMPTZ)
            ORDER BY timestamp_utc DESC
            LIMIT 1
            """,
                [venue, market_id, submitted],
            ).fetchone()
            if row is None:
                continue
            timestamp = _parse_duckdb_timestamp(str(row[2]))
            if best_timestamp is None or timestamp > best_timestamp:
                best_timestamp = timestamp
                best_row = row
        return best_row

    def _validate_snapshot_archive(self) -> None:
        table_dir = self.archive_path / "order_book_snapshots"
        if not table_dir.exists() or not any(table_dir.rglob("*.parquet")):
            raise FileNotFoundError(
                f"No order_book_snapshots parquet files found under {table_dir}"
            )

    def _snapshot_paths(self, *, venue: str, submitted_at: datetime) -> list[Path]:
        table_dir = self.archive_path / "order_book_snapshots" / f"venue={venue}"
        dates = [submitted_at.date(), (submitted_at - timedelta(days=1)).date()]
        paths: list[Path] = []
        for date_value in dates:
            paths.extend(sorted((table_dir / f"date={date_value.isoformat()}").glob("*.parquet")))
        return paths


def _levels(value: Any) -> list[dict[str, float]]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    output: list[dict[str, float]] = []
    for level in value if isinstance(value, list) else []:
        if isinstance(level, dict):
            price = _float_or_none(level.get("price"))
            size = _float_or_none(level.get("size"))
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price = _float_or_none(level[0])
            size = _float_or_none(level[1])
        else:
            continue
        if price is not None and size is not None:
            output.append({"price": price, "size": size})
    return output


def _parse_duckdb_timestamp(value: str) -> datetime:
    text = value.replace(" ", "T")
    if text.endswith("-00"):
        text = text[:-3] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _ensure_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parquet_list_sql(paths: list[Path]) -> str:
    return "[" + ", ".join(_sql_string(str(path)) for path in paths) + "]"


def _chunks(paths: list[Path], size: int) -> list[list[Path]]:
    return [paths[index : index + size] for index in range(0, len(paths), size)]
