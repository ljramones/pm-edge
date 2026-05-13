"""Train a calibrated GBDT probability model from saved signal rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from models import GBDTTrainer, TrainerConfig
from utils import configure_logging, resolve_repo_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a calibrated GBDT signal model.")
    parser.add_argument("--signals", type=Path, required=True, help="Signal parquet/csv file.")
    parser.add_argument("--output", type=Path, required=True, help="Output model artifact path.")
    parser.add_argument("--min-train-rows", type=int, default=200)
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--learning-rate", type=float, default=0.035)
    parser.add_argument("--random-state", type=int, default=7)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging()
    signals_path = resolve_repo_path(args.signals)
    output_path = resolve_repo_path(args.output)
    frame = load_signal_frame(signals_path)
    trainer = GBDTTrainer(
        TrainerConfig(
            min_train_rows=args.min_train_rows,
            n_estimators=args.n_estimators,
            learning_rate=args.learning_rate,
            random_state=args.random_state,
        )
    )
    artifact = trainer.fit(frame)
    artifact.save(output_path)
    report = artifact.report.to_dict() if artifact.report is not None else {}
    print(json.dumps({"model": str(output_path), **report}, indent=2, sort_keys=True))


def load_signal_frame(path: Path) -> pd.DataFrame:
    """Load parquet or csv signals for model training."""

    if not path.exists():
        raise FileNotFoundError(f"Signal file not found: {path}")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


if __name__ == "__main__":
    main()
