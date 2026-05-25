"""Buffered pyarrow parquet storage for forward-indexed data."""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .schemas import TableName, schema_for_table


class BufferedParquetWriter:
    """Write partitioned parquet files with buffering, dedupe, and atomic renames."""

    def __init__(
        self,
        output_dir: Path,
        *,
        flush_max_records: int = 5_000,
        flush_interval_seconds: float = 30.0,
        max_seen_keys_per_table: int = 20_000,
    ) -> None:
        self.output_dir = output_dir
        self.flush_max_records = flush_max_records
        self.flush_interval_seconds = flush_interval_seconds
        self.max_seen_keys_per_table = max_seen_keys_per_table
        self._buffers: dict[TableName, list[dict[str, Any]]] = defaultdict(list)
        self._seen_keys: dict[TableName, OrderedDict[tuple[Any, ...], None]] = defaultdict(
            OrderedDict
        )
        self._last_flush = datetime.now(tz=UTC)
        self._lock = asyncio.Lock()

    async def load_existing_keys_for_today(self, *, current_date: date | None = None) -> None:
        """Load dedupe keys from today's visible parquet partitions."""

        today = current_date or datetime.now(tz=UTC).date()
        for table in TableName:
            paths = sorted(
                self.output_dir.glob(f"{table.value}/venue=*/date={today.isoformat()}/*.parquet"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in paths:
                parquet = pq.ParquetFile(path)
                for batch in parquet.iter_batches(
                    batch_size=2_048,
                    columns=record_key_columns(table),
                ):
                    for row in batch.to_pylist():
                        self._remember_key(table, record_key(table, row))
                        if len(self._seen_keys[table]) >= self.max_seen_keys_per_table:
                            break
                    if len(self._seen_keys[table]) >= self.max_seen_keys_per_table:
                        break
                if len(self._seen_keys[table]) >= self.max_seen_keys_per_table:
                    break

    async def add_records(
        self,
        table: TableName,
        records: list[dict[str, Any]],
        *,
        bypass_dedup: bool = False,
    ) -> int:
        """Add records to an in-memory buffer and return accepted count.

        ``bypass_dedup`` writes every record unconditionally and does NOT touch
        the dedupe set — used for near-resolution hi-cad capture, where identical
        consecutive books must all be retained and the global dedupe set must stay
        reserved for normal-cadence markets.
        """

        accepted = 0
        async with self._lock:
            for record in records:
                if not bypass_dedup:
                    key = record_key(table, record)
                    if key in self._seen_keys[table]:
                        continue
                    self._remember_key(table, key)
                self._buffers[table].append(record)
                accepted += 1
                if self.pending_record_count >= self.flush_max_records:
                    await self._flush_unlocked()
            if self.flush_due:
                await self._flush_unlocked()
        return accepted

    async def flush(self) -> dict[str, int]:
        """Flush all pending buffers to parquet."""

        async with self._lock:
            return await self._flush_unlocked()

    @property
    def pending_record_count(self) -> int:
        """Return total buffered records across all tables."""

        return sum(len(records) for records in self._buffers.values())

    @property
    def flush_due(self) -> bool:
        """Return whether the time-based flush interval has elapsed."""

        elapsed = (datetime.now(tz=UTC) - self._last_flush).total_seconds()
        return elapsed >= self.flush_interval_seconds

    @property
    def seen_key_count(self) -> int:
        """Return the total number of retained dedupe keys."""

        return sum(len(keys) for keys in self._seen_keys.values())

    def partition_dir(self, table: TableName, *, venue: str, timestamp: datetime) -> Path:
        """Return the partition directory for a record."""

        day = timestamp.astimezone(UTC).date().isoformat()
        return self.output_dir / table.value / f"venue={venue}" / f"date={day}"

    async def _flush_unlocked(self) -> dict[str, int]:
        flushed: dict[str, int] = {}
        for table, records in list(self._buffers.items()):
            if not records:
                continue
            grouped: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
            for record in records:
                ts = table_timestamp(table, record)
                grouped[(str(record["venue"]), ts.astimezone(UTC).date())].append(record)
            for (venue, day), group in grouped.items():
                partition = (
                    self.output_dir / table.value / f"venue={venue}" / f"date={day.isoformat()}"
                )
                partition.mkdir(parents=True, exist_ok=True)
                final_path = (
                    partition
                    / f"part-{datetime.now(tz=UTC).strftime('%H%M%S%f')}-{uuid.uuid4().hex[:8]}.parquet"
                )
                temp_path = partition / f".tmp-{final_path.name}"
                arrow_table = pa.Table.from_pylist(group, schema=schema_for_table(table))
                pq.write_table(arrow_table, temp_path)
                temp_path.replace(final_path)
                flushed[table.value] = flushed.get(table.value, 0) + len(group)
            self._buffers[table] = []
        self._last_flush = datetime.now(tz=UTC)
        return flushed

    def _remember_key(self, table: TableName, key: tuple[Any, ...]) -> None:
        seen = self._seen_keys[table]
        if key in seen:
            seen.move_to_end(key)
            return
        seen[key] = None
        while len(seen) > self.max_seen_keys_per_table:
            seen.popitem(last=False)


def record_key(table: TableName, record: dict[str, Any]) -> tuple[Any, ...]:
    """Return the idempotency key for one record."""

    if table is TableName.ORDER_BOOK_SNAPSHOTS:
        return (
            record.get("venue"),
            record.get("market_id"),
            _timestamp_key(record.get("timestamp_utc")),
        )
    if table is TableName.TRADE_EVENTS:
        trade_id = record.get("trade_id_venue")
        if trade_id:
            return (record.get("venue"), record.get("market_id"), trade_id)
        return (
            record.get("venue"),
            record.get("market_id"),
            record.get("token_id"),
            _timestamp_key(record.get("timestamp_utc")),
            record.get("price"),
            record.get("size"),
            record.get("side"),
        )
    if table is TableName.MARKET_METADATA_SNAPSHOTS:
        return (
            record.get("venue"),
            record.get("market_id"),
            _timestamp_key(record.get("captured_at_utc")),
        )
    raise ValueError(f"Unsupported table: {table}")


def record_key_columns(table: TableName) -> list[str]:
    """Return the minimum parquet columns needed to reconstruct idempotency keys."""

    if table is TableName.ORDER_BOOK_SNAPSHOTS:
        return ["venue", "market_id", "timestamp_utc"]
    if table is TableName.TRADE_EVENTS:
        return [
            "venue",
            "market_id",
            "token_id",
            "timestamp_utc",
            "price",
            "size",
            "side",
            "trade_id_venue",
        ]
    if table is TableName.MARKET_METADATA_SNAPSHOTS:
        return ["venue", "market_id", "captured_at_utc"]
    raise ValueError(f"Unsupported table: {table}")


def table_timestamp(table: TableName, record: dict[str, Any]) -> datetime:
    """Return the timestamp column used for partitioning."""

    column = "captured_at_utc" if table is TableName.MARKET_METADATA_SNAPSHOTS else "timestamp_utc"
    value = record[column]
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value)).astimezone(UTC)


def _timestamp_key(value: Any) -> str:
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()
    return str(value)
