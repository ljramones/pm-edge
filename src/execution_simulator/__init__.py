"""Historical execution simulator for forward-indexer parquet archives."""

from .assumptions import run_all
from .config import SimulatorConfig
from .simulate import simulate_order, simulate_strategy
from .types import (
    AssumptionReport,
    AssumptionResult,
    BookSnapshot,
    FillOutcome,
    OrderSide,
    OrderSpec,
    OrderStatus,
)

__all__ = [
    "AssumptionReport",
    "AssumptionResult",
    "BookSnapshot",
    "FillOutcome",
    "OrderSide",
    "OrderSpec",
    "OrderStatus",
    "SimulatorConfig",
    "run_all",
    "simulate_order",
    "simulate_strategy",
]
