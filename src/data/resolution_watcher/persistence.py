"""Parquet persistence for resolved market outcomes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .schema import ResolvedMarketOutcome, resolved_market_outcome_schema


class ResolutionOutcomeWriter:
    """Write resolved market outcomes to venue/date partitioned parquet."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    async def write(self, outcomes: list[ResolvedMarketOutcome]) -> int:
        """Persist outcomes and return the number of rows written."""

        if not outcomes:
            return 0
        grouped: dict[tuple[str, str], list[ResolvedMarketOutcome]] = {}
        for outcome in outcomes:
            day = _to_utc(outcome.resolution_timestamp_utc).date().isoformat()
            grouped.setdefault((outcome.venue, day), []).append(outcome)
        rows_written = 0
        for (venue, day), group in grouped.items():
            partition = self.output_dir / f"venue={venue}" / f"date={day}"
            partition.mkdir(parents=True, exist_ok=True)
            final_path = (
                partition
                / f"part-{datetime.now(tz=UTC).strftime('%H%M%S%f')}-{uuid.uuid4().hex[:8]}.parquet"
            )
            temp_path = partition / f".tmp-{final_path.name}"
            table = pa.Table.from_pylist(
                [outcome.to_record() for outcome in group],
                schema=resolved_market_outcome_schema(),
            )
            pq.write_table(table, temp_path)
            temp_path.replace(final_path)
            rows_written += len(group)
        return rows_written


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
