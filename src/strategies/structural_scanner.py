"""Lightweight Dutch-book and structural consistency scanner."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict


class StructuralOpportunity(BaseModel):
    """Linked-market structural opportunity."""

    model_config = ConfigDict(frozen=True)

    opportunity_type: str
    market_ids: list[str]
    edge: float
    depth: float
    should_trade: bool
    reason: str


class StructuralScanner:
    """Find simple Dutch-book and linked-tail consistency opportunities."""

    def __init__(self, *, min_depth: float = 10_000.0, min_edge: float = 0.02) -> None:
        self.min_depth = min_depth
        self.min_edge = min_edge

    def scan(self, frame: pd.DataFrame) -> list[StructuralOpportunity]:
        """Scan a signal/order-book frame."""

        opportunities: list[StructuralOpportunity] = []
        if {"event_cluster", "market_probability", "liquidity", "market_id"}.issubset(
            frame.columns
        ):
            for cluster, group in frame.groupby("event_cluster"):
                total = float(group["market_probability"].astype(float).sum())
                depth = float(group["liquidity"].astype(float).min())
                if total < 1 - self.min_edge:
                    opportunities.append(
                        StructuralOpportunity(
                            opportunity_type="sum_lt_1",
                            market_ids=[str(value) for value in group["market_id"].tolist()],
                            edge=1 - total,
                            depth=depth,
                            should_trade=depth >= self.min_depth,
                            reason=f"cluster {cluster} sums to {total:.3f}",
                        )
                    )
                if total > 1 + self.min_edge:
                    opportunities.append(
                        StructuralOpportunity(
                            opportunity_type="sum_gt_1",
                            market_ids=[str(value) for value in group["market_id"].tolist()],
                            edge=total - 1,
                            depth=depth,
                            should_trade=depth >= self.min_depth,
                            reason=f"cluster {cluster} sums to {total:.3f}",
                        )
                    )
        return opportunities
