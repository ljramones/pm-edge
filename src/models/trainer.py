"""Training utilities for real probability models over signal datasets."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import TimeSeriesSplit

from utils.logging import get_logger

logger = get_logger(__name__)

EXCLUDED_FEATURE_COLUMNS = {
    "market_id",
    "question",
    "condition_id",
    "slug",
    "outcome",
    "resolved_at",
    "as_of",
    "venue",
    "model_probability",
    "base_model_probability",
    "advanced_model_probability",
    "trained_model_probability",
    "edge",
    "confidence",
    "reasoning",
    "features",
    "price_source",
    "is_lookahead",
    "historical_price_at",
    "historical_price_age_seconds",
    "liquidity_source",
}


@dataclass(frozen=True)
class TrainerConfig:
    """Controls for calibrated GBDT model training."""

    random_state: int = 7
    n_estimators: int = 400
    learning_rate: float = 0.035
    num_leaves: int = 31
    max_depth: int = -1
    min_child_samples: int = 30
    subsample: float = 0.85
    colsample_bytree: float = 0.85
    reg_lambda: float = 1.0
    n_splits: int = 5
    min_train_rows: int = 200
    min_class_count: int = 5
    max_train_rows: int | None = 10_000
    refit_interval_rows: int = 250
    probability_floor: float = 0.001
    probability_ceiling: float = 0.999


@dataclass
class TrainingReport:
    """Summary of a fitted model."""

    rows: int
    features: int
    oof_rows: int
    brier_score: float | None = None
    log_loss: float | None = None
    feature_importance: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "features": self.features,
            "oof_rows": self.oof_rows,
            "brier_score": self.brier_score,
            "log_loss": self.log_loss,
            "feature_importance": self.feature_importance,
        }


@dataclass
class GBDTModelArtifact:
    """Serializable trained model plus feature metadata and calibration."""

    model: Any
    feature_names: list[str]
    config: TrainerConfig
    calibrator: LogisticRegression | None = None
    report: TrainingReport | None = None

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        """Predict calibrated positive-outcome probabilities for signal rows."""

        features = build_feature_matrix(frame, feature_names=self.feature_names)
        probabilities = raw_positive_probabilities(self.model, features)
        return calibrate_probabilities(
            probabilities,
            calibrator=self.calibrator,
            floor=self.config.probability_floor,
            ceiling=self.config.probability_ceiling,
        )

    def save(self, path: Path) -> None:
        """Persist the model artifact and sidecar metadata files."""

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(self, handle)
        if self.report is not None:
            metadata_path = path.with_suffix(path.suffix + ".metadata.json")
            metadata_path.write_text(json.dumps(self.report.to_dict(), indent=2, sort_keys=True))
            importance = pd.Series(self.report.feature_importance, name="importance")
            if not importance.empty:
                importance.sort_values(ascending=False).to_csv(
                    path.with_suffix(path.suffix + ".feature_importance.csv"),
                    header=True,
                )

    @classmethod
    def load(cls, path: Path) -> GBDTModelArtifact:
        """Load a saved model artifact."""

        with path.open("rb") as handle:
            artifact = pickle.load(handle)
        if not isinstance(artifact, cls):
            raise TypeError(f"Unexpected model artifact type in {path}: {type(artifact)!r}")
        return artifact


class GBDTTrainer:
    """Train calibrated LightGBM-style probability models on signal rows."""

    def __init__(self, config: TrainerConfig | None = None) -> None:
        self.config = config or TrainerConfig()

    def fit(self, frame: pd.DataFrame) -> GBDTModelArtifact:
        """Fit a calibrated binary probability model."""

        prepared = prepare_training_frame(frame)
        if len(prepared) < self.config.min_train_rows:
            raise ValueError(
                f"Need at least {self.config.min_train_rows} training rows, got {len(prepared)}."
            )
        target = prepared["outcome"].astype(int)
        if target.nunique() < 2:
            raise ValueError("Training requires both positive and negative resolved outcomes.")
        if int(target.value_counts().min()) < self.config.min_class_count:
            raise ValueError(
                "Training requires at least "
                f"{self.config.min_class_count} examples of each class."
            )

        features = build_feature_matrix(prepared)
        feature_names = list(features.columns)
        oof = self._walk_forward_oof(features, target)
        calibrator = fit_platt_calibrator(oof, target, self.config)
        model = self._fit_estimator(features, target)
        report = TrainingReport(
            rows=len(prepared),
            features=len(feature_names),
            oof_rows=int(oof.notna().sum()),
            brier_score=metric_or_none("brier", target[oof.notna()], oof.dropna()),
            log_loss=metric_or_none("log_loss", target[oof.notna()], oof.dropna()),
            feature_importance=feature_importance(model, feature_names),
        )
        logger.info(
            "gbdt_trainer_fit",
            rows=report.rows,
            features=report.features,
            oof_rows=report.oof_rows,
            brier_score=report.brier_score,
            log_loss=report.log_loss,
        )
        return GBDTModelArtifact(
            model=model,
            feature_names=feature_names,
            config=self.config,
            calibrator=calibrator,
            report=report,
        )

    def predict_walk_forward(
        self,
        frame: pd.DataFrame,
        *,
        model_output: Path | None = None,
    ) -> tuple[pd.DataFrame, GBDTModelArtifact | None]:
        """Predict each timestamp using only outcomes resolved before that timestamp."""

        output = frame.copy()
        if output.empty:
            return output, None
        output["as_of"] = pd.to_datetime(output["as_of"], utc=True, errors="coerce")
        output["resolved_at"] = pd.to_datetime(output["resolved_at"], utc=True, errors="coerce")
        output["outcome"] = pd.to_numeric(output["outcome"], errors="coerce")
        if "reasoning" not in output.columns:
            output["reasoning"] = ""
        output = output.sort_values(["as_of", "market_id"]).reset_index(drop=True)

        predictions = pd.Series(np.nan, index=output.index, dtype=float)
        last_train_index: tuple[int, int] | None = None
        artifact: GBDTModelArtifact | None = None
        trained_timestamps = 0
        for as_of, indices in output.groupby("as_of", sort=True).groups.items():
            as_of_ts = pd.Timestamp(as_of)
            train_mask = (
                output["resolved_at"].notna()
                & output["outcome"].notna()
                & (output["resolved_at"] < as_of_ts)
            )
            train_frame = output.loc[train_mask]
            if (
                self.config.max_train_rows is not None
                and len(train_frame) > self.config.max_train_rows
            ):
                train_frame = train_frame.tail(self.config.max_train_rows)
            refit_interval = max(1, self.config.refit_interval_rows)
            outcome_classes = int(pd.to_numeric(train_frame["outcome"], errors="coerce").nunique())
            key = (len(train_frame) // refit_interval, outcome_classes)
            if len(train_frame) < self.config.min_train_rows:
                continue
            if key != last_train_index:
                artifact = self._fit_or_none(train_frame)
                last_train_index = key
                if artifact is not None:
                    trained_timestamps += 1
            if artifact is None:
                continue
            predict_frame = output.loc[list(indices)]
            predictions.loc[list(indices)] = artifact.predict_proba(predict_frame)

        predicted_mask = predictions.notna()
        if predicted_mask.any():
            output.loc[predicted_mask, "model_probability"] = predictions.loc[predicted_mask]
            output.loc[predicted_mask, "trained_model_probability"] = predictions.loc[
                predicted_mask
            ]
            output.loc[predicted_mask, "edge"] = output.loc[
                predicted_mask, "model_probability"
            ].astype(float) - output.loc[predicted_mask, "market_probability"].astype(float)
            output.loc[predicted_mask, "confidence"] = (
                output.loc[predicted_mask, "edge"].abs() / 0.10
            ).clip(0.0, 1.0)
            output.loc[predicted_mask, "base_model_probability"] = predictions.loc[predicted_mask]
            output.loc[predicted_mask, "advanced_model_probability"] = predictions.loc[
                predicted_mask
            ]
            output.loc[predicted_mask, "reasoning"] = output.loc[predicted_mask, "reasoning"].map(
                append_trained_reasoning
            )
        if artifact is not None and model_output is not None:
            artifact.save(model_output)
        logger.info(
            "gbdt_walk_forward_predictions",
            rows=len(output),
            predicted_rows=int(predicted_mask.sum()),
            trained_timestamps=trained_timestamps,
            model_output=str(model_output) if model_output else None,
        )
        return output, artifact

    def _fit_or_none(self, frame: pd.DataFrame) -> GBDTModelArtifact | None:
        try:
            return self.fit(frame)
        except ValueError as exc:
            logger.info("gbdt_train_skipped", rows=len(frame), reason=str(exc))
            return None

    def _walk_forward_oof(self, features: pd.DataFrame, target: pd.Series) -> pd.Series:
        split_count = min(self.config.n_splits, max(2, len(features) // self.config.min_train_rows))
        splitter = TimeSeriesSplit(n_splits=split_count)
        oof = pd.Series(np.nan, index=features.index, dtype=float)
        for train_idx, validation_idx in splitter.split(features):
            y_train = target.iloc[train_idx]
            y_validation = target.iloc[validation_idx]
            if y_train.nunique() < 2 or y_validation.nunique() < 2:
                continue
            model = self._fit_estimator(features.iloc[train_idx], y_train)
            oof.iloc[validation_idx] = raw_positive_probabilities(
                model, features.iloc[validation_idx]
            )
        return oof

    def _fit_estimator(self, features: pd.DataFrame, target: pd.Series) -> Any:
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            model = HistGradientBoostingClassifier(
                learning_rate=self.config.learning_rate,
                max_iter=self.config.n_estimators,
                random_state=self.config.random_state,
            )
            return model.fit(features, target.astype(int))

        model = LGBMClassifier(
            objective="binary",
            n_estimators=self.config.n_estimators,
            learning_rate=self.config.learning_rate,
            num_leaves=self.config.num_leaves,
            max_depth=self.config.max_depth,
            min_child_samples=self.config.min_child_samples,
            subsample=self.config.subsample,
            colsample_bytree=self.config.colsample_bytree,
            reg_lambda=self.config.reg_lambda,
            random_state=self.config.random_state,
            verbose=-1,
        )
        return model.fit(features, target.astype(int))


def prepare_training_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return rows with resolved outcomes and valid timestamps."""

    output = frame.copy()
    required = {"as_of", "resolved_at", "outcome", "market_probability"}
    missing = required - set(output.columns)
    if missing:
        raise ValueError(f"Training frame missing required columns: {sorted(missing)}")
    output["as_of"] = pd.to_datetime(output["as_of"], utc=True, errors="coerce")
    output["resolved_at"] = pd.to_datetime(output["resolved_at"], utc=True, errors="coerce")
    output["outcome"] = pd.to_numeric(output["outcome"], errors="coerce")
    output["market_probability"] = pd.to_numeric(output["market_probability"], errors="coerce")
    output = output.dropna(subset=["as_of", "resolved_at", "outcome", "market_probability"])
    output = output[output["outcome"].isin([0, 1])]
    if "is_lookahead" in output:
        output = output[~output["is_lookahead"].fillna(False).astype(bool)]
    return output.sort_values(["as_of", "market_id"]).reset_index(drop=True)


def build_feature_matrix(
    frame: pd.DataFrame, *, feature_names: list[str] | None = None
) -> pd.DataFrame:
    """Build numeric model features from top-level columns and nested feature dicts."""

    features = pd.DataFrame(index=frame.index)
    for column in frame.columns:
        if column in EXCLUDED_FEATURE_COLUMNS:
            continue
        if pd.api.types.is_numeric_dtype(frame[column]):
            features[column] = pd.to_numeric(frame[column], errors="coerce")
    nested = flatten_feature_dicts(frame.get("features"))
    if not nested.empty:
        for column in nested.columns:
            features[f"feature__{column}"] = pd.to_numeric(nested[column], errors="coerce")
    for column in ["market_probability", "liquidity", "volume", "fear_sizing_multiplier"]:
        if column in frame and column not in features:
            features[column] = pd.to_numeric(frame[column], errors="coerce")
    features = features.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if feature_names is not None:
        for column in feature_names:
            if column not in features:
                features[column] = 0.0
        features = features[feature_names]
    return features.astype(float)


def flatten_feature_dicts(values: pd.Series | None) -> pd.DataFrame:
    """Flatten the nested `features` dict column into a numeric DataFrame."""

    if values is None:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, dict):
            rows.append(value)
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                rows.append({})
            else:
                rows.append(parsed if isinstance(parsed, dict) else {})
        else:
            rows.append({})
    return pd.DataFrame(rows, index=values.index)


def raw_positive_probabilities(model: Any, features: pd.DataFrame) -> np.ndarray:
    """Return uncalibrated positive probabilities from a classifier."""

    if hasattr(model, "predict_proba"):
        return cast(np.ndarray, model.predict_proba(features)[:, 1])
    scores = model.predict(features)
    return cast(np.ndarray, np.clip(scores, 0.001, 0.999))


def fit_platt_calibrator(
    oof_probabilities: pd.Series, target: pd.Series, config: TrainerConfig
) -> LogisticRegression | None:
    """Fit Platt scaling on walk-forward out-of-fold predictions."""

    valid = oof_probabilities.dropna()
    if len(valid) < max(20, config.min_train_rows // 4):
        return None
    y = target.loc[valid.index].astype(int)
    if y.nunique() < 2:
        return None
    calibrator = LogisticRegression(random_state=config.random_state)
    calibrator.fit(logit(valid.to_numpy()).reshape(-1, 1), y)
    return calibrator


def calibrate_probabilities(
    probabilities: np.ndarray,
    *,
    calibrator: LogisticRegression | None,
    floor: float,
    ceiling: float,
) -> np.ndarray:
    """Apply optional Platt scaling and clip probabilities."""

    clipped = np.clip(probabilities, floor, ceiling)
    if calibrator is None:
        return cast(np.ndarray, clipped)
    calibrated = calibrator.predict_proba(logit(clipped).reshape(-1, 1))[:, 1]
    return cast(np.ndarray, np.clip(calibrated, floor, ceiling))


def logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(probabilities.astype(float), 0.001, 0.999)
    return cast(np.ndarray, np.log(clipped / (1.0 - clipped)))


def feature_importance(model: Any, feature_names: list[str]) -> dict[str, float]:
    """Return normalized feature importance when available."""

    values = getattr(model, "feature_importances_", None)
    if values is None:
        return {}
    raw = {name: float(value) for name, value in zip(feature_names, values, strict=False)}
    total = sum(abs(value) for value in raw.values()) or 1.0
    return {name: value / total for name, value in raw.items()}


def metric_or_none(name: str, target: pd.Series, probability: pd.Series) -> float | None:
    """Compute a metric when the inputs are valid."""

    if len(target) == 0 or len(probability) == 0 or target.nunique() < 2:
        return None
    if name == "brier":
        return float(brier_score_loss(target.astype(int), probability.astype(float)))
    if name == "log_loss":
        return float(log_loss(target.astype(int), probability.astype(float), labels=[0, 1]))
    return None


def append_trained_reasoning(value: Any) -> str:
    """Add a trained-model note to a reasoning field."""

    if isinstance(value, list):
        base = [str(item) for item in value]
    elif value is None or pd.isna(value):
        base = []
    else:
        base = [str(value)]
    notes = [item for item in base if item and "bootstrap" not in item.lower()]
    notes.append("gbdt walk-forward trained probability")
    return "; ".join(notes)
