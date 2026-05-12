from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from core import UnifiedMarket, Venue
from execution import PaperTrader, PaperTraderConfig
from monitoring import AlertManager
from monitoring.alerts import AlertConfig
from strategies import EdgeSignal


class FakeClient:
    def __init__(self, markets: list[UnifiedMarket]) -> None:
        self.markets = markets

    async def fetch_markets(self, venues: Any = None) -> list[UnifiedMarket]:
        return self.markets


class FakeDetector:
    def __init__(self, signals: dict[str, EdgeSignal]) -> None:
        self.signals = signals

    async def score_market(
        self,
        market: UnifiedMarket,
        *,
        market_probability: float | None = None,
        model_context: Any = None,
    ) -> EdgeSignal:
        return self.signals[market.market_id]


@pytest.mark.asyncio
async def test_paper_trader_run_once_persists_target_position(tmp_path) -> None:
    market = UnifiedMarket(
        venue=Venue.POLYMARKET,
        market_id="m-1",
        title="Will event happen?",
        status="open",
        raw={"volume": 1_000_000, "liquidity": 500_000},
    )
    signal = EdgeSignal(
        market_id="m-1",
        market_prob=0.45,
        model_prob=0.55,
        edge=0.10,
        confidence=0.8,
        reasoning=["test"],
    )
    trader = PaperTrader(
        PaperTraderConfig(
            state_path=tmp_path / "state.json",
            audit_log_path=tmp_path / "audit.jsonl",
            review_mode=False,
            min_volume=500_000,
            virtual_capital=10_000,
        ),
        client=FakeClient([market]),  # type: ignore[arg-type]
        detector=FakeDetector({"m-1": signal}),  # type: ignore[arg-type]
        alert_manager=AlertManager(AlertConfig(console_enabled=False)),
    )

    result = await trader.run_once()
    await trader.close()

    assert result.signal_count == 1
    assert result.target_count == 1
    assert (tmp_path / "state.json").exists()
    assert "m-1" in trader.state.positions
    assert trader.state.positions["m-1"].target_notional > 0


@pytest.mark.asyncio
async def test_paper_trader_review_timeout_blocks_unapproved_trade(tmp_path) -> None:
    market = UnifiedMarket(
        venue=Venue.KALSHI,
        market_id="m-2",
        title="Will large edge happen?",
        status="open",
        raw={"volume": 1_000_000, "liquidity": 1_000_000},
    )
    signal = EdgeSignal(
        market_id="m-2",
        market_prob=0.40,
        model_prob=0.55,
        edge=0.15,
        confidence=0.9,
    )
    trader = PaperTrader(
        PaperTraderConfig(
            state_path=tmp_path / "state.json",
            audit_log_path=tmp_path / "audit.jsonl",
            review_flag_path=tmp_path / "approval.txt",
            review_mode=True,
            review_threshold=0.08,
            review_timeout_seconds=1,
            min_volume=0,
        ),
        client=FakeClient([market]),  # type: ignore[arg-type]
        detector=FakeDetector({"m-2": signal}),  # type: ignore[arg-type]
        alert_manager=AlertManager(AlertConfig(console_enabled=False)),
    )

    started = datetime.now()
    result = await trader.run_once()
    await trader.close()

    assert (datetime.now() - started).total_seconds() < 3
    assert result.decisions[0].requires_review is True
    assert result.decisions[0].approved is False
    assert trader.state.positions == {}
