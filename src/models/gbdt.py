"""LightGBM probability model with time-series validation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit

from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LightGBMProbabilityModel:
    """LightGBM classifier with sigmoid calibration.

    If LightGBM is unavailable in a local environment, this class falls back to
    sklearn's histogram gradient boosting classifier while preserving the same
    public API.
    """

    objective: str = "binary"
    n_estimators: int = 200
    learning_rate: float = 0.05
    random_state: int = 7
    feature_names: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.model = CalibratedClassifierCV(
            estimator=self._build_estimator(),
            method="sigmoid",
            cv=TimeSeriesSplit(n_splits=3),
        )

    def fit(self, features: pd.DataFrame, target: pd.Series) -> LightGBMProbabilityModel:
        """Fit calibrated GBDT model without future leakage."""

        self.feature_names = list(features.columns)
        self.model.fit(features, target.astype(int))
        logger.info("gbdt_model_fit", rows=len(features), features=len(self.feature_names))
        return self

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """Return probabilities for the positive outcome."""

        return cast(
            np.ndarray,
            self.model.predict_proba(features[self.feature_names or list(features.columns)])[:, 1],
        )

    def feature_importances(self) -> dict[str, float]:
        """Return feature importances when exposed by the fitted estimator."""

        importances: dict[str, float] = {}
        for calibrated in getattr(self.model, "calibrated_classifiers_", []):
            estimator = getattr(calibrated, "estimator", None)
            values = getattr(estimator, "feature_importances_", None)
            if values is None:
                continue
            for name, value in zip(self.feature_names, values, strict=False):
                importances[name] = importances.get(name, 0.0) + float(value)
        if importances:
            scale = sum(importances.values()) or 1.0
            importances = {key: value / scale for key, value in importances.items()}
            logger.info("gbdt_feature_importance", importances=importances)
        return importances

    def _build_estimator(self) -> object:
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            return HistGradientBoostingClassifier(
                learning_rate=self.learning_rate,
                max_iter=self.n_estimators,
                random_state=self.random_state,
            )

        return LGBMClassifier(
            objective=self.objective,
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            verbose=-1,
        )
