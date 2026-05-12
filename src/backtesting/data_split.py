"""Time-series-safe walk-forward splitting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict


class WalkForwardSplit(BaseModel):
    """One walk-forward train/test interval."""

    model_config = ConfigDict(frozen=True)

    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(frozen=True)
class WalkForwardConfig:
    """Configuration for rolling or expanding walk-forward splits."""

    train_window_days: int = 180
    test_window_days: int = 30
    step_days: int = 30
    mode: Literal["expanding", "rolling"] = "expanding"
    min_train_observations: int = 30


class WalkForwardSplitter:
    """Generate deterministic time-series splits without future leakage."""

    def __init__(self, config: WalkForwardConfig | None = None) -> None:
        self.config = config or WalkForwardConfig()

    def split(
        self,
        frame: pd.DataFrame,
        *,
        time_column: str = "as_of",
        resolution_column: str = "resolved_at",
    ) -> list[WalkForwardSplit]:
        """Return walk-forward intervals that only train on resolved prior rows."""

        if frame.empty:
            return []
        for column in [time_column, resolution_column]:
            if column not in frame.columns:
                raise ValueError(f"Missing required column: {column}")

        data = frame.copy()
        data[time_column] = pd.to_datetime(data[time_column], utc=True)
        data[resolution_column] = pd.to_datetime(data[resolution_column], utc=True)
        start = data[time_column].min()
        end = data[time_column].max()
        train_delta = pd.Timedelta(days=self.config.train_window_days)
        test_delta = pd.Timedelta(days=self.config.test_window_days)
        step_delta = pd.Timedelta(days=self.config.step_days)

        splits: list[WalkForwardSplit] = []
        cursor = start + train_delta
        while cursor < end:
            train_start = start if self.config.mode == "expanding" else cursor - train_delta
            train_end = cursor
            test_start = cursor
            test_end = min(cursor + test_delta, end + pd.Timedelta(microseconds=1))

            train_rows = data[
                (data[time_column] >= train_start)
                & (data[time_column] < train_end)
                & (data[resolution_column] <= train_end)
            ]
            test_rows = data[(data[time_column] >= test_start) & (data[time_column] < test_end)]

            if len(train_rows) >= self.config.min_train_observations and not test_rows.empty:
                splits.append(
                    WalkForwardSplit(
                        train_start=train_start.to_pydatetime(),
                        train_end=train_end.to_pydatetime(),
                        test_start=test_start.to_pydatetime(),
                        test_end=test_end.to_pydatetime(),
                    )
                )
            cursor += step_delta

        return splits
