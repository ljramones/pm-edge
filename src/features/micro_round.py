"""Feature extraction for short-duration crypto micro-round markets."""

from __future__ import annotations

from typing import Any


class MicroRoundFeatureExtractor:
    """Build maker/liquidity features for 5-15 minute market rounds."""

    def extract(self, row: dict[str, Any]) -> dict[str, float]:
        """Return stable micro-round and maker-advantage features."""

        duration = _num(row.get("duration_minutes"), default=1440.0)
        yes_no_sum = _num(row.get("yes_no_sum"), default=1.0)
        spread = _num(row.get("spread"), default=0.0)
        volume = _num(row.get("volume"), default=0.0)
        liquidity = _num(row.get("liquidity"), row.get("top_book_liquidity"), default=0.0)
        incentive = _num(row.get("incentive"), row.get("rewards"), default=0.0)
        market_probability = _bounded(
            _num(row.get("market_probability"), default=0.5), 0.001, 0.999
        )

        is_micro = 1.0 if 0.0 < duration <= 15.0 else 0.0
        is_short = 1.0 if 0.0 < duration <= 60.0 else 0.0
        duration_decay = 1.0 / max(duration, 1.0)
        sum_excess = max(0.0, yes_no_sum - 1.0)
        depth_proxy = max(liquidity, volume * 0.005, 1.0)
        maker_advantage = sum_excess + spread * 0.5 + incentive / max(duration, 1.0)
        adverse_fill_risk = min(5.0, volume / depth_proxy) * duration_decay
        tail_zone = 1.0 if 0.08 <= market_probability <= 0.12 else 0.0
        return {
            "micro_duration_minutes": duration,
            "micro_is_5_15m": is_micro,
            "micro_is_subhour": is_short,
            "micro_duration_decay": duration_decay,
            "micro_yes_no_sum": yes_no_sum,
            "micro_sum_excess": sum_excess,
            "micro_incentive_multiplier": incentive / max(duration, 1.0),
            "micro_maker_advantage_score": maker_advantage,
            "micro_adverse_fill_risk": adverse_fill_risk,
            "micro_tail_zone_8_12c": tail_zone,
            "micro_depth_proxy": depth_proxy,
        }


def _num(*values: Any, default: float = 0.0) -> float:
    for value in values:
        if value is None:
            continue
        try:
            if value != value:
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
