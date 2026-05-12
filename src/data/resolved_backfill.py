"""Resolved-market sample expansion utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class BackfillConfig(BaseModel):
    """Controls for resolved-market backfill loading and deduplication."""

    model_config = ConfigDict(frozen=True)

    input_paths: list[Path] = Field(default_factory=list)
    min_resolved_at: datetime | None = None
    max_resolved_at: datetime | None = None


class ResolvedMarketBackfill:
    """Load and normalize resolved market rows from local historical files."""

    def __init__(self, config: BackfillConfig | None = None) -> None:
        self.config = config or BackfillConfig()

    def load(self) -> pd.DataFrame:
        """Load all configured files into a deduplicated signal-like frame."""

        frames = [read_frame(path) for path in self.config.input_paths]
        if not frames:
            return pd.DataFrame()
        frame = pd.concat(frames, ignore_index=True)
        frame["as_of"] = pd.to_datetime(frame["as_of"], utc=True)
        frame["resolved_at"] = pd.to_datetime(frame["resolved_at"], utc=True)
        if self.config.min_resolved_at is not None:
            frame = frame[frame["resolved_at"] >= _utc_timestamp(self.config.min_resolved_at)]
        if self.config.max_resolved_at is not None:
            frame = frame[frame["resolved_at"] <= _utc_timestamp(self.config.max_resolved_at)]
        return frame.drop_duplicates(subset=["market_id", "as_of"]).reset_index(drop=True)


def read_frame(path: Path) -> pd.DataFrame:
    """Read one CSV or parquet file."""

    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return pd.Timestamp(value)
