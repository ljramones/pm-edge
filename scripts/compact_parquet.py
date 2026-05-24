"""Compact forward-index and resolved-outcome parquet part-files.

The forward indexer and resolution watcher each write a new parquet part-file
per ``(table, venue, date)`` partition on every flush (~every 15 s). After a
week a single partition directory holds thousands of tiny files, which makes
recursive ``read_parquet('.../**/*.parquet')`` globs hang, slows ext4 directory
lookups, and makes rsync metadata sync crawl. This job merges the many small
same-partition part-files into a few large ones, without data loss.

Safety model
------------
* **Never touch today's partition.** Only partitions strictly older than today
  (UTC) are compacted, so the live writer is never raced.
* **Verify before delete.** The compacted output row count must equal the sum
  of the input row counts before any source file is removed.
* **Crash-safe atomic replace.** Each compacted file is written to a hidden
  ``.tmp-compact-*`` file, then renamed to its final ``compact-*`` name (the
  durable commit marker), and only then are the source ``part-*`` files
  deleted. A crash between the rename and the deletes is self-healed on the
  next run, which removes the leftover ``part-*`` duplicates already captured in
  the ``compact-*`` file.
* **Idempotent.** A partition that already consists only of ``compact-*`` files
  (or a single file) is skipped.

Run ``--dry-run`` first to see what would be compacted without writing or
deleting anything.
"""

from __future__ import annotations

import argparse
import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from core.config import get_settings
from data.resolution_watcher.settings import ResolutionWatcherSettings
from utils.logging import configure_logging, get_logger

DEFAULT_TARGET_FILE_BYTES = 256 * 1024 * 1024
COMPACT_PREFIX = "compact-"
TEMP_PREFIX = ".tmp-compact-"

logger = get_logger(__name__)


class CompactionVerificationError(RuntimeError):
    """Raised when the compacted output row count does not match the input."""

    def __init__(self, partition: str, input_rows: int, output_rows: int) -> None:
        super().__init__(
            f"row-count mismatch for {partition}: "
            f"inputs={input_rows} output={output_rows}; sources preserved"
        )
        self.partition = partition
        self.input_rows = input_rows
        self.output_rows = output_rows


@dataclass(frozen=True)
class Partition:
    """A single ``date=`` partition directory holding parquet part-files."""

    path: Path
    date: date
    label: str


@dataclass(frozen=True)
class PartitionResult:
    """Outcome of considering one partition for compaction."""

    partition: str
    action: str
    files_before: int = 0
    files_after: int = 0
    rows: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    error: str | None = None

    @property
    def files_removed(self) -> int:
        return max(0, self.files_before - self.files_after)


# Action constants (kept as plain strings so they serialise cleanly in logs).
ACTION_COMPACTED = "compacted"
ACTION_RECOVERED = "recovered_leftovers"
ACTION_SKIPPED_TODAY = "skipped_today_or_future"
ACTION_SKIPPED_EMPTY = "skipped_empty"
ACTION_SKIPPED_SINGLE = "skipped_single_file"
ACTION_SKIPPED_ALREADY = "skipped_already_compact"
ACTION_WOULD_COMPACT = "would_compact"
ACTION_WOULD_RECOVER = "would_recover_leftovers"
ACTION_FAILED = "failed"


# --------------------------------------------------------------------------- #
# Partition discovery and file classification
# --------------------------------------------------------------------------- #
def _parse_partition_date(dir_name: str) -> date | None:
    if not dir_name.startswith("date="):
        return None
    try:
        return date.fromisoformat(dir_name[len("date=") :])
    except ValueError:
        return None


def discover_partitions(root: Path) -> list[Partition]:
    """Return every ``date=`` partition under ``root`` without descending into it.

    Works for both the forward-index layout
    (``{table}/venue=.../date=.../``) and the resolved-outcomes layout
    (``venue=.../date=.../``).
    """

    partitions: list[Partition] = []
    if not root.exists():
        return partitions
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            parsed = _parse_partition_date(entry.name)
            if parsed is not None:
                label = f"{root.name}/{entry.relative_to(root)}"
                partitions.append(Partition(path=entry, date=parsed, label=label))
                # A date partition holds part-files only; never descend into it.
            else:
                stack.append(entry)
    return partitions


def _parquet_files(partition_dir: Path) -> list[Path]:
    return [p for p in partition_dir.iterdir() if p.is_file() and p.name.endswith(".parquet")]


def raw_files(partition_dir: Path) -> list[Path]:
    """Return the writer's raw ``part-*`` files (excludes compact and temp)."""

    return sorted(
        p
        for p in _parquet_files(partition_dir)
        if not p.name.startswith(".") and not p.name.startswith(COMPACT_PREFIX)
    )


def compact_files(partition_dir: Path) -> list[Path]:
    """Return already-compacted ``compact-*`` files."""

    return sorted(p for p in _parquet_files(partition_dir) if p.name.startswith(COMPACT_PREFIX))


def _temp_files(partition_dir: Path) -> list[Path]:
    return sorted(p for p in _parquet_files(partition_dir) if p.name.startswith("."))


def _total_bytes(paths: Iterable[Path]) -> int:
    return sum(p.stat().st_size for p in paths)


def _row_count(path: Path) -> int:
    return int(pq.read_metadata(path).num_rows)


def _total_rows(paths: Iterable[Path]) -> int:
    return sum(_row_count(p) for p in paths)


# --------------------------------------------------------------------------- #
# Compaction
# --------------------------------------------------------------------------- #
def _generation_id() -> str:
    return f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _cleanup_generation(partition_dir: Path, generation: str) -> None:
    for path in _parquet_files(partition_dir):
        if path.name.startswith(f"{TEMP_PREFIX}{generation}"):
            path.unlink(missing_ok=True)


def _write_compacted_files(
    partition_dir: Path,
    source_files: list[Path],
    *,
    target_file_bytes: int,
    generation: str,
) -> list[Path]:
    """Merge ``source_files`` into one or more size-capped temp files.

    Reads one part-file at a time (each is a single small flush) and accumulates
    them in a buffer, so peak memory stays bounded to roughly ``target_file_bytes``
    regardless of how large the partition is. When the buffer reaches the target
    size it is concatenated and written as one parquet file, then a new file is
    started. Every input is cast to the canonical schema so the output schema is
    stable. Returns the temp file paths, not yet promoted to ``compact-*`` names.
    """

    target_schema = pq.read_schema(source_files[0])
    temp_files: list[Path] = []
    buffer: list[pa.Table] = []
    buffer_bytes = 0
    next_index = 0

    def _flush() -> None:
        nonlocal buffer, buffer_bytes, next_index
        if not buffer:
            return
        combined = pa.concat_tables(buffer)
        buffer = []
        buffer_bytes = 0
        temp = partition_dir / f"{TEMP_PREFIX}{generation}-{next_index:04d}.parquet"
        pq.write_table(combined, temp)
        temp_files.append(temp)
        next_index += 1

    for source in source_files:
        table = pq.ParquetFile(source).read()
        if table.schema != target_schema:
            table = table.cast(target_schema)
        buffer.append(table)
        buffer_bytes += table.nbytes
        if buffer_bytes >= target_file_bytes:
            _flush()
    _flush()
    return temp_files


def _final_name(temp_name: str) -> str:
    return temp_name.replace(TEMP_PREFIX, COMPACT_PREFIX, 1)


def compact_partition(
    partition: Partition,
    *,
    target_file_bytes: int = DEFAULT_TARGET_FILE_BYTES,
    dry_run: bool = False,
) -> PartitionResult:
    """Compact one partition. Raises ``CompactionVerificationError`` on mismatch.

    The caller is responsible for skipping today's/future partitions; this
    function operates on whatever partition it is given.
    """

    partition_dir = partition.path
    raw = raw_files(partition_dir)
    compact = compact_files(partition_dir)
    bytes_before = _total_bytes(raw) + _total_bytes(compact)

    # Already compacted and no raw leftovers: nothing to do.
    if compact and not raw:
        return PartitionResult(
            partition=partition.label,
            action=ACTION_SKIPPED_ALREADY,
            files_before=len(compact),
            files_after=len(compact),
            bytes_before=bytes_before,
            bytes_after=bytes_before,
        )

    # Compact files plus raw leftovers: a crash interrupted a prior run between
    # promoting the compacted file and deleting its sources. The compact-* file
    # already contains those rows (it is only created after verification), so the
    # leftover raw files are safe to delete.
    if compact and raw:
        if dry_run:
            return PartitionResult(
                partition=partition.label,
                action=ACTION_WOULD_RECOVER,
                files_before=len(raw) + len(compact),
                files_after=len(compact),
                bytes_before=bytes_before,
            )
        for path in raw:
            path.unlink(missing_ok=True)
        bytes_after = _total_bytes(compact_files(partition_dir))
        return PartitionResult(
            partition=partition.label,
            action=ACTION_RECOVERED,
            files_before=len(raw) + len(compact),
            files_after=len(compact),
            rows=_total_rows(compact_files(partition_dir)),
            bytes_before=bytes_before,
            bytes_after=bytes_after,
        )

    # From here there are no compact files.
    if not raw:
        return PartitionResult(
            partition=partition.label,
            action=ACTION_SKIPPED_EMPTY,
        )
    if len(raw) == 1:
        return PartitionResult(
            partition=partition.label,
            action=ACTION_SKIPPED_SINGLE,
            files_before=1,
            files_after=1,
            rows=_row_count(raw[0]),
            bytes_before=bytes_before,
            bytes_after=bytes_before,
        )

    input_rows = _total_rows(raw)

    if dry_run:
        estimated_after = max(1, math.ceil(bytes_before / target_file_bytes))
        return PartitionResult(
            partition=partition.label,
            action=ACTION_WOULD_COMPACT,
            files_before=len(raw),
            files_after=estimated_after,
            rows=input_rows,
            bytes_before=bytes_before,
        )

    # Clear any stale temp files from a previously crashed run, then write fresh.
    for stale in _temp_files(partition_dir):
        stale.unlink(missing_ok=True)

    generation = _generation_id()
    try:
        temp_files = _write_compacted_files(
            partition_dir,
            raw,
            target_file_bytes=target_file_bytes,
            generation=generation,
        )
        output_rows = _total_rows(temp_files)
        if output_rows != input_rows:
            raise CompactionVerificationError(partition.label, input_rows, output_rows)
    except BaseException:
        _cleanup_generation(partition_dir, generation)
        raise

    # Promote temp files to their final names (atomic), then delete sources.
    final_files: list[Path] = []
    for temp in temp_files:
        final = partition_dir / _final_name(temp.name)
        temp.replace(final)
        final_files.append(final)
    for path in raw:
        path.unlink(missing_ok=True)

    return PartitionResult(
        partition=partition.label,
        action=ACTION_COMPACTED,
        files_before=len(raw),
        files_after=len(final_files),
        rows=input_rows,
        bytes_before=bytes_before,
        bytes_after=_total_bytes(final_files),
    )


def compact_root(
    root: Path,
    *,
    today: date,
    target_file_bytes: int = DEFAULT_TARGET_FILE_BYTES,
    dry_run: bool = False,
) -> list[PartitionResult]:
    """Compact every past partition under ``root``; never touches ``today``."""

    results: list[PartitionResult] = []
    partitions = sorted(discover_partitions(root), key=lambda p: (p.date, str(p.path)))
    for partition in partitions:
        if partition.date >= today:
            results.append(PartitionResult(partition=partition.label, action=ACTION_SKIPPED_TODAY))
            continue
        try:
            result = compact_partition(
                partition,
                target_file_bytes=target_file_bytes,
                dry_run=dry_run,
            )
        except Exception as exc:  # verification or IO failure: keep going
            result = PartitionResult(
                partition=partition.label,
                action=ACTION_FAILED,
                error=str(exc),
            )
            logger.error(
                "parquet_compaction_partition_failed",
                partition=partition.label,
                error=str(exc),
            )
        if result.action in {
            ACTION_COMPACTED,
            ACTION_RECOVERED,
            ACTION_WOULD_COMPACT,
            ACTION_WOULD_RECOVER,
        }:
            logger.info(
                "parquet_compaction_partition",
                partition=result.partition,
                action=result.action,
                files_before=result.files_before,
                files_after=result.files_after,
                rows=result.rows,
                bytes_before=result.bytes_before,
                bytes_after=result.bytes_after,
                dry_run=dry_run,
            )
        results.append(result)
    return results


def _log_summary(root: Path, results: list[PartitionResult], *, dry_run: bool) -> None:
    compacted = [r for r in results if r.action in {ACTION_COMPACTED, ACTION_WOULD_COMPACT}]
    failures = [r for r in results if r.action == ACTION_FAILED]
    logger.info(
        "parquet_compaction_summary",
        root=str(root),
        partitions_scanned=len(results),
        partitions_compacted=len(compacted),
        partitions_skipped=len(results) - len(compacted) - len(failures),
        files_removed=sum(r.files_removed for r in results),
        rows_total=sum(r.rows for r in compacted),
        bytes_before=sum(r.bytes_before for r in results),
        bytes_after=sum(r.bytes_after for r in results),
        failures=len(failures),
        dry_run=dry_run,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        default=None,
        help=(
            "Archive root to compact (repeatable). Defaults to the configured "
            "forward-index and resolved-outcome directories."
        ),
    )
    parser.add_argument(
        "--target-file-mb",
        type=float,
        default=DEFAULT_TARGET_FILE_BYTES / (1024 * 1024),
        help="Approximate maximum size of each compacted file in MiB.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be compacted without writing or deleting.",
    )
    return parser.parse_args(argv)


def _default_roots() -> list[Path]:
    return [
        get_settings().forward_indexer_output_dir,
        ResolutionWatcherSettings().output_dir,
    ]


def main(argv: list[str] | None = None) -> int:
    """Compact configured (or supplied) archive roots; return a process exit code."""

    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        json_logs=settings.log_json,
        http_log_level=settings.http_log_level,
    )
    args = parse_args(argv)
    roots = args.root if args.root else _default_roots()
    target_file_bytes = max(1, int(args.target_file_mb * 1024 * 1024))
    today = datetime.now(tz=UTC).date()

    failures = 0
    for root in roots:
        results = compact_root(
            root,
            today=today,
            target_file_bytes=target_file_bytes,
            dry_run=args.dry_run,
        )
        _log_summary(root, results, dry_run=args.dry_run)
        failures += sum(1 for r in results if r.action == ACTION_FAILED)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
