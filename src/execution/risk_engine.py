"""Hardened risk controls and Monte Carlo ruin simulation."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class MonteCarloRuinResult(BaseModel):
    """Monte Carlo survival diagnostics."""

    model_config = ConfigDict(frozen=True)

    simulations: int
    periods: int
    ruin_threshold: float
    ruin_probability: float
    median_final_equity: float
    p05_final_equity: float
    p95_final_equity: float


class MonteCarloRuinSimulator:
    """Bootstrap realized PnL paths to estimate risk of ruin."""

    def __init__(
        self,
        *,
        starting_capital: float = 10_000.0,
        ruin_threshold: float = 0.50,
        simulations: int = 1_000,
        seed: int = 17,
    ) -> None:
        self.starting_capital = starting_capital
        self.ruin_threshold = ruin_threshold
        self.simulations = simulations
        self.seed = seed

    def run(self, pnl: pd.Series) -> MonteCarloRuinResult:
        """Run Monte Carlo ruin simulation from historical PnL observations."""

        values = pnl.astype(float).to_numpy()
        if len(values) == 0:
            return MonteCarloRuinResult(
                simulations=self.simulations,
                periods=0,
                ruin_threshold=self.ruin_threshold,
                ruin_probability=0.0,
                median_final_equity=self.starting_capital,
                p05_final_equity=self.starting_capital,
                p95_final_equity=self.starting_capital,
            )
        rng = np.random.default_rng(self.seed)
        finals = []
        ruined = 0
        ruin_level = self.starting_capital * self.ruin_threshold
        for _ in range(self.simulations):
            path = (
                self.starting_capital + rng.choice(values, size=len(values), replace=True).cumsum()
            )
            finals.append(float(path[-1]))
            ruined += int(float(path.min()) <= ruin_level)
        return MonteCarloRuinResult(
            simulations=self.simulations,
            periods=len(values),
            ruin_threshold=self.ruin_threshold,
            ruin_probability=ruined / self.simulations,
            median_final_equity=float(np.median(finals)),
            p05_final_equity=float(np.quantile(finals, 0.05)),
            p95_final_equity=float(np.quantile(finals, 0.95)),
        )


class HardenedRiskConfig(BaseModel):
    """Non-negotiable Phase 8 risk gates."""

    model_config = ConfigDict(frozen=True)

    min_post_cost_edge: float = 0.05
    cash_buffer: float = 0.30
    max_event_cluster_exposure: float = 0.12
    adverse_selection_buffer: float = 0.20
    kelly_fraction: float = Field(default=0.25, ge=0.0, le=0.25)
