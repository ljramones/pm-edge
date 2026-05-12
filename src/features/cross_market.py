"""Cross-market correlation and divergence features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class CrossMarketFeatureSet(BaseModel):
    """Computed cross-market features for one market."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    related_market_id: str | None = None
    price_divergence: float = 0.0
    rolling_corr_7d: float = 0.0
    rolling_corr_30d: float = 0.0
    lead_lag_corr_1d: float = 0.0
    implied_conditional_probability: float = 0.5
    raw: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class CrossMarketAnalyzer:
    """Compute relationship features from historical price snapshots."""

    min_periods: int = 3

    def compute(
        self,
        prices: pd.DataFrame,
        *,
        target_market_id: str,
        related_market_id: str | None = None,
    ) -> CrossMarketFeatureSet:
        """Compute cross-market features for a target market."""

        if prices.empty:
            return CrossMarketFeatureSet(
                market_id=target_market_id, related_market_id=related_market_id
            )

        wide = pivot_market_prices(prices)
        if target_market_id not in wide:
            return CrossMarketFeatureSet(
                market_id=target_market_id, related_market_id=related_market_id
            )

        target = wide[target_market_id].dropna()
        if target.empty:
            return CrossMarketFeatureSet(
                market_id=target_market_id, related_market_id=related_market_id
            )

        related = related_market_id or _most_correlated_market(
            wide, target_market_id, self.min_periods
        )
        if related is None or related not in wide:
            return CrossMarketFeatureSet(market_id=target_market_id)

        aligned = pd.concat([wide[target_market_id], wide[related]], axis=1).dropna()
        aligned.columns = ["target", "related"]
        if len(aligned) < self.min_periods:
            return CrossMarketFeatureSet(market_id=target_market_id, related_market_id=related)

        latest_target = float(aligned["target"].iloc[-1])
        latest_related = float(aligned["related"].iloc[-1])
        corr_7d = _rolling_corr(aligned["target"], aligned["related"], 7, self.min_periods)
        corr_30d = _rolling_corr(aligned["target"], aligned["related"], 30, self.min_periods)
        lead_lag = aligned["target"].shift(1).corr(aligned["related"])
        conditional = _bounded_probability(
            latest_target * max(corr_30d, 0.0) + latest_related * 0.25
        )

        return CrossMarketFeatureSet(
            market_id=target_market_id,
            related_market_id=related,
            price_divergence=latest_target - latest_related,
            rolling_corr_7d=_finite(corr_7d),
            rolling_corr_30d=_finite(corr_30d),
            lead_lag_corr_1d=_finite(float(lead_lag)),
            implied_conditional_probability=conditional,
            raw={"observations": len(aligned)},
        )


def pivot_market_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Pivot normalized price history into a timestamp x market matrix."""

    required = {"market_id", "observed_at"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Missing required price columns: {sorted(missing)}")

    value_column = "mid"
    if value_column not in prices.columns:
        if {"bid", "ask"}.issubset(prices.columns):
            prices = prices.copy()
            prices[value_column] = (prices["bid"] + prices["ask"]) / 2
        elif "last" in prices.columns:
            value_column = "last"
        else:
            raise ValueError("Price frame requires mid, bid/ask, or last.")

    frame = prices.copy()
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    return (
        frame.pivot_table(
            index="observed_at",
            columns="market_id",
            values=value_column,
            aggfunc="last",
        )
        .sort_index()
        .ffill()
    )


def _most_correlated_market(
    wide: pd.DataFrame,
    target_market_id: str,
    min_periods: int,
) -> str | None:
    correlations = wide.corr(min_periods=min_periods)[target_market_id].drop(
        labels=[target_market_id]
    )
    correlations = correlations.dropna()
    if correlations.empty:
        return None
    return str(correlations.abs().idxmax())


def _rolling_corr(left: pd.Series, right: pd.Series, window: int, min_periods: int) -> float:
    value = left.rolling(window=window, min_periods=min_periods).corr(right).iloc[-1]
    return _finite(float(value))


def _finite(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return value


def _bounded_probability(value: float) -> float:
    return max(0.01, min(0.99, value))
