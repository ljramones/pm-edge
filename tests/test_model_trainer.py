from pathlib import Path

import numpy as np
import pandas as pd

from models import GBDTModelArtifact, GBDTTrainer, TrainerConfig


def test_gbdt_trainer_fits_saves_and_loads_model(tmp_path: Path) -> None:
    frame = training_frame(rows=260)
    trainer = GBDTTrainer(TrainerConfig(min_train_rows=80, n_estimators=20, n_splits=3))

    artifact = trainer.fit(frame)
    output = tmp_path / "model.pkl"
    artifact.save(output)
    loaded = GBDTModelArtifact.load(output)
    probabilities = loaded.predict_proba(frame.tail(5))

    assert output.exists()
    assert output.with_suffix(".pkl.metadata.json").exists()
    assert len(loaded.feature_names) > 0
    assert probabilities.shape == (5,)
    assert ((probabilities > 0.0) & (probabilities < 1.0)).all()


def test_gbdt_trainer_walk_forward_replaces_bootstrap_probabilities() -> None:
    frame = training_frame(rows=320)
    trainer = GBDTTrainer(TrainerConfig(min_train_rows=60, n_estimators=20, n_splits=3))

    output, _artifact = trainer.predict_walk_forward(frame)

    predicted = output["trained_model_probability"].notna()
    assert predicted.any()
    assert output.loc[predicted, "model_probability"].ne(0.5).any()
    assert np.allclose(
        output.loc[predicted, "edge"],
        output.loc[predicted, "model_probability"] - output.loc[predicted, "market_probability"],
    )


def training_frame(*, rows: int) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    outcomes = [index % 2 for index in range(rows)]
    probabilities = [0.35 + (index % 7) * 0.04 for index in range(rows)]
    return pd.DataFrame(
        {
            "market_id": [f"m-{index}" for index in range(rows)],
            "question": [f"Will BTC signal {index} resolve yes?" for index in range(rows)],
            "as_of": dates,
            "resolved_at": dates + pd.Timedelta(days=1),
            "venue": ["polymarket"] * rows,
            "market_probability": probabilities,
            "model_probability": [0.5] * rows,
            "edge": [0.0] * rows,
            "confidence": [0.1] * rows,
            "outcome": outcomes,
            "liquidity": [10_000 + index for index in range(rows)],
            "volume": [100_000 + index * 10 for index in range(rows)],
            "fear_sizing_multiplier": [1.0] * rows,
            "features": [
                {
                    "llm_probability": 0.45 + 0.1 * outcome,
                    "llm_news_score": -0.1 + 0.2 * outcome,
                    "onchain_volume_surge": float(index % 5),
                }
                for index, outcome in enumerate(outcomes)
            ],
        }
    )
