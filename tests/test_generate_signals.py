from pathlib import Path

import pandas as pd

from scripts.generate_signals import iter_timestamps, partition_path, write_demo_signals


def test_generate_signals_demo_writes_partitioned_parquet(tmp_path: Path) -> None:
    timestamps = iter_timestamps("2025-03-01", "2025-03-01", 6)

    write_demo_signals(timestamps, output=tmp_path, overwrite=False)
    path = partition_path(tmp_path, timestamps[0])

    assert path.exists()
    frame = pd.read_parquet(path)
    assert {"market_id", "model_probability", "market_probability"}.issubset(frame.columns)


def test_generate_signals_demo_can_include_advanced_features(tmp_path: Path) -> None:
    timestamps = iter_timestamps("2025-03-01", "2025-03-01", 6)

    write_demo_signals(timestamps, output=tmp_path, overwrite=False, include_advanced=True)
    frame = pd.read_parquet(partition_path(tmp_path, timestamps[0]))

    assert frame["advanced_enabled"].all()
    assert "llm_probability" in frame.iloc[0]["features"]
