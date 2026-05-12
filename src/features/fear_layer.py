"""Fear layer and market-temperature routing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class FearSnapshot(BaseModel):
    """Global market fear state."""

    model_config = ConfigDict(frozen=True)

    vix: float = 20.0
    cnn_fear_greed: float = 50.0
    crypto_fear_greed: float = 50.0

    @property
    def fear_score(self) -> float:
        """Return normalized fear in [0, 1]."""

        vix_component = min(max((self.vix - 12) / 38, 0.0), 1.0)
        cnn_component = 1 - min(max(self.cnn_fear_greed / 100, 0.0), 1.0)
        crypto_component = 1 - min(max(self.crypto_fear_greed / 100, 0.0), 1.0)
        return 0.35 * vix_component + 0.25 * cnn_component + 0.40 * crypto_component


class MarketTemperature(BaseModel):
    """Per-market attention/liquidity temperature."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    effective_attention: float
    temperature: float
    sizing_multiplier: float
    route: bool
    reason: str


class FearLayerRouter:
    """Route and size markets based on global fear and per-market temperature."""

    def __init__(
        self,
        *,
        min_effective_attention: float = 100.0,
        max_temperature: float = 0.02,
    ) -> None:
        self.min_effective_attention = min_effective_attention
        self.max_temperature = max_temperature

    def evaluate(
        self,
        *,
        market_id: str,
        liquidity: float,
        volume: float,
        spread: float = 0.0,
        fear: FearSnapshot | None = None,
    ) -> MarketTemperature:
        """Return routing and sizing state for one market."""

        snapshot = fear or FearSnapshot()
        effective = max(
            (liquidity**0.5) * (1 + volume / max(liquidity, 1.0)) / (1 + spread * 10), 1e-9
        )
        temperature = 1 / effective
        route = effective >= self.min_effective_attention and temperature <= self.max_temperature
        multiplier = max(
            0.25,
            min(
                1.25,
                (1 - temperature / max(self.max_temperature, 1e-9)) + snapshot.fear_score * 0.35,
            ),
        )
        return MarketTemperature(
            market_id=market_id,
            effective_attention=effective,
            temperature=temperature,
            sizing_multiplier=multiplier if route else 0.0,
            route=route,
            reason="route" if route else "reject: thin/hot market",
        )

    def features(
        self, row: dict[str, object], *, fear: FearSnapshot | None = None
    ) -> dict[str, float]:
        """Return numeric fear-layer features for a signal row."""

        state = self.evaluate(
            market_id=str(row.get("market_id")),
            liquidity=_as_float(row.get("liquidity", 0.0)),
            volume=_as_float(row.get("volume", 0.0)),
            spread=_as_float(row.get("spread", 0.0)),
            fear=fear,
        )
        snapshot = fear or FearSnapshot()
        return {
            "fear_score": snapshot.fear_score,
            "market_temperature": state.temperature,
            "effective_attention": state.effective_attention,
            "fear_sizing_multiplier": state.sizing_multiplier,
            "fear_route": 1.0 if state.route else 0.0,
        }


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
