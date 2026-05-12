"""Baseline probability models for Phase 1 edge scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


class ProbabilityModel(Protocol):
    """Protocol shared by baseline and GBDT probability models."""

    def fit(self, features: pd.DataFrame, target: pd.Series) -> ProbabilityModel:
        """Fit model and return self."""

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """Return probabilities for the positive outcome."""


@dataclass
class LogisticBaseline:
    """Calibrated logistic regression baseline."""

    max_iter: int = 1000

    def __post_init__(self) -> None:
        estimator = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("logistic", LogisticRegression(max_iter=self.max_iter)),
            ]
        )
        self.model = CalibratedClassifierCV(estimator=estimator, method="sigmoid", cv=3)

    def fit(self, features: pd.DataFrame, target: pd.Series) -> LogisticBaseline:
        self.model.fit(features, target.astype(int))
        return self

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        return cast(np.ndarray, self.model.predict_proba(features)[:, 1])


@dataclass
class RidgeProbabilityBaseline:
    """Ridge regression clipped into calibrated probability space."""

    alpha: float = 1.0

    def __post_init__(self) -> None:
        self.model = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("ridge", Ridge(alpha=self.alpha)),
            ]
        )

    def fit(self, features: pd.DataFrame, target: pd.Series) -> RidgeProbabilityBaseline:
        self.model.fit(features, target.astype(float))
        return self

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        return cast(np.ndarray, np.clip(self.model.predict(features), 0.01, 0.99))


@dataclass
class ICWeightedFactorModel:
    """Information-coefficient weighted factor combination baseline."""

    min_abs_weight: float = 1e-6

    def fit(self, features: pd.DataFrame, target: pd.Series) -> ICWeightedFactorModel:
        correlations = features.apply(lambda column: column.corr(target.astype(float))).fillna(0.0)
        weights = correlations.clip(lower=-1.0, upper=1.0)
        if weights.abs().sum() < self.min_abs_weight:
            weights = pd.Series(1.0 / len(features.columns), index=features.columns)
        else:
            weights = weights / weights.abs().sum()
        self.weights = weights
        self.bias = float(target.mean())
        return self

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        centered = features - features.mean(axis=0)
        scale = features.std(axis=0).replace(0, 1.0)
        score = (centered / scale).dot(self.weights)
        probability = 1 / (1 + np.exp(-(score + self._logit(self.bias))))
        return cast(np.ndarray, np.clip(probability.to_numpy(), 0.01, 0.99))

    def _logit(self, probability: float) -> float:
        clipped = min(max(probability, 0.01), 0.99)
        return float(np.log(clipped / (1 - clipped)))


def average_probabilities(probability_sets: list[np.ndarray]) -> np.ndarray:
    """Return simple ensemble average of probability arrays."""

    if not probability_sets:
        raise ValueError("At least one probability set is required.")
    return cast(np.ndarray, np.mean(np.vstack(probability_sets), axis=0))
