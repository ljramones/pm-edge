"""Configuration for the conservative v0 execution simulator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SimulatorConfig:
    """Conservative-by-design simulator configuration.

    These values are conservative-by-design. They may be relaxed only with
    documented justification, never to improve backtest results.
    """

    max_book_age_seconds: int = 60
    """Maximum age of the book snapshot accepted for a fill decision.

    Default is conservative: a book more than 60 seconds old is treated as
    untradeable rather than interpolated from later state.
    """

    taker_fee_bps: int = 50
    """Fee applied to marketable orders in basis points.

    Default is intentionally high for v0. It approximates a venue-maximum
    taker cost until venue-specific fee calibration is justified.
    """

    maker_fee_bps: int = 0
    """Fee applied to resting orders in basis points.

    Resting fills are disabled by default in v0, so this is only used when
    `allow_resting_fills` is explicitly enabled in later experiments.
    """

    allow_resting_fills: bool = False
    """Whether resting orders can fill.

    Default is False because v0 assumes worst-case queue position and does not
    model queue priority.
    """

    slippage_model: Literal["full_spread", "half_spread", "none"] = "full_spread"
    """Slippage accounting mode.

    Default records the full difference between fill price and mid/limit,
    which is the pessimistic choice for marketable orders crossing the spread.
    """

    require_complete_top_book: bool = True
    """Require both top bid and top ask before simulating a fill.

    Default is conservative: incomplete top-of-book state is treated as
    unfillable instead of assuming the missing side would have been available.
    """
