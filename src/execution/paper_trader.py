"""Live paper trading orchestration for edge signals and Kelly targets."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core import BackendUnavailableError, PredictionMarketClient, UnifiedMarket, Venue
from core.config import Settings, get_settings
from core.models import utc_now
from data import LLMNewsProcessor, NewsSentimentEngine, OnChainProcessor
from data.llm_news_processor import LLMProvider
from data.onchain_processor import infer_asset_symbol
from execution.portfolio import KellyFractionalPortfolio, KellyPortfolioConfig, TargetPosition
from features import FearLayerRouter, FearSnapshot, FeatureStore
from monitoring import AlertManager, PerformanceTracker, TelegramNotifier
from strategies import EdgeDetector, EdgeSignal, LiquidityProvider, LiquidityProviderConfig
from utils.logging import get_logger

logger = get_logger(__name__)


class PaperTraderConfig(BaseModel):
    """Runtime and risk controls for live paper trading."""

    model_config = ConfigDict(frozen=True)

    interval_seconds: int = Field(default=900, ge=1)
    virtual_capital: float = Field(default=10_000.0, gt=0)
    min_volume: float = Field(default=500_000.0, ge=0.0)
    max_markets: int = Field(default=50, ge=1)
    kelly_fraction: float = Field(default=0.35, ge=0.0, le=1.0)
    max_exposure: float = Field(default=0.25, ge=0.0, le=1.0)
    max_position_weight: float = Field(default=0.05, ge=0.0, le=1.0)
    min_edge: float = Field(default=0.02, ge=0.0)
    review_mode: bool = True
    review_threshold: float = Field(default=0.08, ge=0.0)
    review_timeout_seconds: int = Field(default=0, ge=0)
    review_flag_path: Path = Path("data/processed/live_paper/review_approval.txt")
    state_path: Path = Path("data/processed/live_paper/state.json")
    audit_log_path: Path = Path("data/processed/live_paper/audit.jsonl")
    use_advanced_features: bool = False
    use_llm: bool = False
    use_onchain: bool = False
    llm_provider: LLMProvider = "ollama"
    articles_per_market: int = Field(default=6, ge=0)
    crypto_only: bool = False
    mode: Literal["directional", "liquidity-only"] = "directional"
    liquidity_min_edge: float = Field(default=0.08, ge=0.0)
    liquidity_adverse_buffer: float = Field(default=0.25, ge=0.0)
    liquidity_max_tail_exposure: float = Field(default=0.06, ge=0.0, le=1.0)


class PaperLivePosition(BaseModel):
    """Open paper position marked to current market probability."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    venue: Venue
    direction: int
    size: float
    average_price: float
    current_price: float
    target_notional: float
    edge: float
    confidence: float
    opened_at: datetime
    updated_at: datetime
    title: str | None = None

    @property
    def signed_notional(self) -> float:
        """Return current signed notional exposure."""

        return self.direction * abs(self.target_notional)

    @property
    def unrealized_pnl(self) -> float:
        """Return mark-to-market PnL for the binary paper position."""

        if self.direction > 0:
            return (self.current_price - self.average_price) * self.size
        return (self.average_price - self.current_price) * self.size


class PaperTradeDecision(BaseModel):
    """Audit record for one target-vs-current paper action."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    market_id: str
    action: str
    current_notional: float
    target_notional: float
    delta_notional: float
    edge: float
    confidence: float
    requires_review: bool = False
    approved: bool = True
    reason: str = ""


class PaperTraderState(BaseModel):
    """Persisted live paper trading state."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime = Field(default_factory=utc_now)
    virtual_capital: float
    cash: float
    equity: float
    positions: dict[str, PaperLivePosition] = Field(default_factory=dict)
    last_signals: list[dict[str, Any]] = Field(default_factory=list)
    latest_performance: dict[str, Any] = Field(default_factory=dict)


class PaperTraderCycleResult(BaseModel):
    """Output from one live paper trading cycle."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    market_count: int
    signal_count: int
    target_count: int
    decisions: list[PaperTradeDecision]
    equity: float
    state_path: Path


class PaperTrader:
    """Run the live paper loop: markets -> signals -> Kelly targets -> paper decisions."""

    def __init__(
        self,
        config: PaperTraderConfig | None = None,
        *,
        settings: Settings | None = None,
        client: PredictionMarketClient | None = None,
        detector: EdgeDetector | None = None,
        allocator: KellyFractionalPortfolio | None = None,
        alert_manager: AlertManager | None = None,
        performance_tracker: PerformanceTracker | None = None,
        news_engine: NewsSentimentEngine | None = None,
        llm_processor: LLMNewsProcessor | None = None,
        onchain_processor: OnChainProcessor | None = None,
        telegram_notifier: TelegramNotifier | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config = config or config_from_settings(self.settings)
        self.client = client or PredictionMarketClient(settings=self.settings)
        self._owns_client = client is None
        self.detector = detector or EdgeDetector(
            FeatureStore(client=self.client),
            use_advanced_features=self.config.use_advanced_features
            or self.config.use_llm
            or self.config.use_onchain,
        )
        self.allocator = allocator or KellyFractionalPortfolio(
            KellyPortfolioConfig(
                kelly_fraction=self.config.kelly_fraction,
                max_total_exposure=self.config.max_exposure,
                max_position_weight=self.config.max_position_weight,
                min_edge=self.config.min_edge,
            )
        )
        self.alert_manager = alert_manager or AlertManager(settings=self.settings)
        self.telegram_notifier = telegram_notifier or TelegramNotifier(settings=self.settings)
        self.performance_tracker = performance_tracker or PerformanceTracker()
        self.news_engine = news_engine
        if self.news_engine is None and self.config.use_llm:
            self.news_engine = NewsSentimentEngine(settings=self.settings)
        self.llm_processor = llm_processor
        if self.llm_processor is None and self.config.use_llm:
            self.llm_processor = LLMNewsProcessor(settings=self.settings)
        self.onchain_processor = onchain_processor
        if self.onchain_processor is None and self.config.use_onchain:
            self.onchain_processor = OnChainProcessor(settings=self.settings)
        self.liquidity_provider = LiquidityProvider(
            LiquidityProviderConfig(
                starting_capital=self.config.virtual_capital,
                max_notional=self.config.virtual_capital * self.config.max_position_weight,
                max_cluster_exposure=min(self.config.max_exposure, 0.08),
                max_tail_exposure=min(self.config.liquidity_max_tail_exposure, 0.06),
                min_post_fee_edge=max(self.config.liquidity_min_edge, 0.08),
                min_tail_post_fee_edge=max(self.config.liquidity_min_edge, 0.10),
                adverse_selection_buffer=self.config.liquidity_adverse_buffer,
            )
        )
        self.state = self._load_state()
        self._last_summary_day: date | None = None

    async def close(self) -> None:
        """Close owned network resources."""

        if self._owns_client:
            await self.client.close()
        await self.alert_manager.close()
        await self.telegram_notifier.close()
        if self.news_engine is not None:
            await self.news_engine.close()
        if self.llm_processor is not None:
            await self.llm_processor.close()
        if self.onchain_processor is not None:
            await self.onchain_processor.close()

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        """Run cycles until cancelled or a stop event is set."""

        event = stop_event or asyncio.Event()
        while not event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("paper_trader_cycle_failed", error=str(exc))
                await self.alert_manager.send("Paper trader cycle failed", str(exc))
            await self._maybe_daily_summary()
            try:
                await asyncio.wait_for(event.wait(), timeout=self.config.interval_seconds)
            except TimeoutError:
                continue

    async def run_once(self) -> PaperTraderCycleResult:
        """Execute one live paper trading cycle."""

        as_of = utc_now()
        markets = await self._fetch_markets()
        signals = (
            await self._liquidity_signals(markets, as_of=as_of)
            if self.config.mode == "liquidity-only"
            else await self._score_markets(markets, as_of=as_of)
        )
        targets = self.allocator.allocate(
            signals,
            capital=self.config.virtual_capital,
            liquidity=_liquidity_by_market(markets),
        )
        decisions = await self._apply_targets(
            targets, markets=markets, signals=signals, as_of=as_of
        )
        snapshot = self.performance_tracker.record(
            signals=signals,
            equity=self._equity(),
            unrealized_pnl=self._unrealized_pnl(),
            as_of=as_of,
        )
        self.state = PaperTraderState(
            as_of=as_of,
            virtual_capital=self.config.virtual_capital,
            cash=self.config.virtual_capital,
            equity=self._equity(),
            positions=self.state.positions,
            last_signals=[_signal_summary(signal) for signal in signals[:25]],
            latest_performance=snapshot.model_dump(mode="json"),
        )
        self._persist_state()
        self._append_audit(
            {
                "as_of": as_of.isoformat(),
                "event": "cycle_complete",
                "market_count": len(markets),
                "signal_count": len(signals),
                "target_count": len(targets),
                "decision_count": len(decisions),
                "equity": self.state.equity,
                "rubric_grade": snapshot.rubric.grade,
            }
        )
        await self._alert_if_needed(signals, snapshot.degradation_flags)
        return PaperTraderCycleResult(
            as_of=as_of,
            market_count=len(markets),
            signal_count=len(signals),
            target_count=len(targets),
            decisions=decisions,
            equity=self.state.equity,
            state_path=self.config.state_path,
        )

    async def _fetch_markets(self) -> list[UnifiedMarket]:
        try:
            markets = await self.client.fetch_markets()
        except BackendUnavailableError:
            raise
        filtered = [
            market
            for market in markets
            if _market_volume(market) >= self.config.min_volume
            and (market.status or "open").lower() in {"open", "active", "trading"}
            and (not self.config.crypto_only or infer_asset_symbol(market) is not None)
        ]
        return sorted(filtered, key=_market_volume, reverse=True)[: self.config.max_markets]

    async def _score_markets(
        self, markets: Sequence[UnifiedMarket], *, as_of: datetime
    ) -> list[EdgeSignal]:
        signals: list[EdgeSignal] = []
        for market in markets:
            try:
                context = await self._advanced_context(market, as_of=as_of)
                signal = await self.detector.score_market(market, model_context=context)
            except Exception as exc:
                logger.warning(
                    "paper_trader_market_score_failed",
                    market_id=market.market_id,
                    error=str(exc),
                )
                continue
            signals.append(signal)
        return sorted(
            signals, key=lambda signal: abs(signal.edge) * signal.confidence, reverse=True
        )

    async def _liquidity_signals(
        self, markets: Sequence[UnifiedMarket], *, as_of: datetime
    ) -> list[EdgeSignal]:
        """Return paper quote signals from the liquidity harvester only."""

        router = FearLayerRouter()
        fear = FearSnapshot(vix=28, cnn_fear_greed=35, crypto_fear_greed=30)
        signals: list[EdgeSignal] = []
        for market in markets:
            row = _liquidity_market_row(market)
            row.update(router.features(row, fear=fear))
            opportunity = self.liquidity_provider.evaluate(row)
            self._append_audit(
                {
                    "as_of": as_of.isoformat(),
                    "event": "liquidity_opportunity_evaluated",
                    **opportunity.model_dump(mode="json"),
                }
            )
            if not opportunity.should_quote:
                continue
            await self.telegram_notifier.liquidity_opportunity(
                market_id=opportunity.market_id,
                spread=opportunity.spread,
                incentive=opportunity.incentive_score,
                edge=opportunity.post_fee_edge,
                link=opportunity.link,
            )
            market_probability = float(row["market_probability"])
            model_probability = min(
                max(market_probability + opportunity.post_fee_edge, 0.001), 0.999
            )
            signals.append(
                EdgeSignal(
                    market_id=market.market_id,
                    market_prob=market_probability,
                    model_prob=model_probability,
                    edge=model_probability - market_probability,
                    confidence=min(opportunity.post_fee_edge / 0.10, 1.0),
                    reasoning=[opportunity.reason, opportunity.opportunity_type],
                    features={
                        "top_book_liquidity": float(row["liquidity"]),
                        "liquidity_post_fee_edge": opportunity.post_fee_edge,
                        "adverse_selection_score": opportunity.adverse_selection_score,
                        "fear_sizing_multiplier": opportunity.fear_sizing_multiplier,
                    },
                )
            )
        return sorted(
            signals, key=lambda signal: abs(signal.edge) * signal.confidence, reverse=True
        )

    async def _advanced_context(self, market: UnifiedMarket, *, as_of: datetime) -> dict[str, Any]:
        context: dict[str, Any] = {"as_of": as_of}
        articles = []
        if self.config.use_llm and self.news_engine and self.llm_processor:
            try:
                fetched = await self.news_engine.fetch_gdelt(
                    market.title, max_records=max(self.config.articles_per_market * 3, 1)
                )
                articles = [
                    article
                    for article in fetched
                    if article.published_at <= as_of
                    and (as_of - article.published_at).total_seconds() <= 7 * 24 * 3600
                ][: self.config.articles_per_market]
            except Exception as exc:
                logger.warning(
                    "paper_trader_news_fetch_failed", market_id=market.market_id, error=str(exc)
                )
            context["llm_summary"] = await self.llm_processor.summarize_market(
                market_id=market.market_id,
                market_title=market.title,
                articles=articles,
                provider=self.config.llm_provider,
                as_of=as_of,
            )
            context["news_velocity"] = {
                "6h": float(
                    sum(
                        1
                        for article in articles
                        if (as_of - article.published_at).total_seconds() <= 6 * 3600
                    )
                ),
                "24h": float(
                    sum(
                        1
                        for article in articles
                        if (as_of - article.published_at).total_seconds() <= 24 * 3600
                    )
                ),
                "7d": float(len(articles)),
            }
        if self.config.use_onchain and self.onchain_processor:
            context["onchain_snapshot"] = await self.onchain_processor.fetch_market_metrics(
                market, as_of=as_of
            )
        return context

    async def _apply_targets(
        self,
        targets: Sequence[TargetPosition],
        *,
        markets: Sequence[UnifiedMarket],
        signals: Sequence[EdgeSignal],
        as_of: datetime,
    ) -> list[PaperTradeDecision]:
        market_by_id = {market.market_id: market for market in markets}
        signal_by_id = {signal.market_id: signal for signal in signals}
        target_by_id = {target.market_id: target for target in targets}
        all_market_ids = set(self.state.positions) | set(target_by_id)
        decisions: list[PaperTradeDecision] = []
        next_positions = dict(self.state.positions)

        for market_id in sorted(all_market_ids):
            target = target_by_id.get(market_id)
            signal = signal_by_id.get(market_id)
            current = self.state.positions.get(market_id)
            current_notional = current.signed_notional if current else 0.0
            target_notional = (
                target.direction * target.target_notional if target is not None else 0.0
            )
            delta = target_notional - current_notional
            if abs(delta) < 1.0:
                continue

            edge = signal.edge if signal else 0.0
            requires_review = self.config.review_mode and abs(edge) >= self.config.review_threshold
            approved = not requires_review or await self._wait_for_review(market_id, edge)
            decision = PaperTradeDecision(
                as_of=as_of,
                market_id=market_id,
                action=_action_from_delta(delta, target_notional),
                current_notional=current_notional,
                target_notional=target_notional,
                delta_notional=delta,
                edge=edge,
                confidence=signal.confidence if signal else 0.0,
                requires_review=requires_review,
                approved=approved,
                reason="approved" if approved else "review_not_approved",
            )
            decisions.append(decision)
            self._append_audit({"event": "trade_decision", **decision.model_dump(mode="json")})
            logger.info("paper_trade_decision", **decision.model_dump(mode="json"))
            if not approved:
                continue
            if target is None or abs(target_notional) <= 0:
                next_positions.pop(market_id, None)
                continue
            market = market_by_id[market_id]
            price = max(min(target.market_prob, 0.99), 0.01)
            next_positions[market_id] = PaperLivePosition(
                market_id=market_id,
                venue=market.venue,
                direction=target.direction,
                size=abs(target.target_notional) / price,
                average_price=price if current is None else current.average_price,
                current_price=price,
                target_notional=abs(target.target_notional),
                edge=target.edge,
                confidence=target.confidence,
                opened_at=current.opened_at if current else as_of,
                updated_at=as_of,
                title=market.title,
            )

        self.state = self.state.model_copy(update={"positions": next_positions, "as_of": as_of})
        return decisions

    async def _wait_for_review(self, market_id: str, edge: float) -> bool:
        message = (
            f"Review required for {market_id} edge={edge:.3f}. "
            f"Write '{market_id}' or 'approve_all' to {self.config.review_flag_path}."
        )
        await self.alert_manager.send("Paper review required", message)
        start = datetime.now(tz=UTC)
        while True:
            if self.config.review_flag_path.exists():
                content = self.config.review_flag_path.read_text().strip()
                approvals = {item.strip() for item in content.replace(",", "\n").splitlines()}
                if market_id in approvals or "approve_all" in approvals:
                    return True
            if self.config.review_timeout_seconds:
                elapsed = (datetime.now(tz=UTC) - start).total_seconds()
                if elapsed >= self.config.review_timeout_seconds:
                    return False
            await asyncio.sleep(2)

    async def _alert_if_needed(self, signals: Sequence[EdgeSignal], flags: Sequence[str]) -> None:
        if signals and abs(signals[0].edge) >= self.config.review_threshold:
            top = signals[0]
            await self.alert_manager.send(
                "Large paper opportunity",
                f"{top.market_id}: edge={top.edge:.3f}, confidence={top.confidence:.3f}",
                payload=top.model_dump(mode="json"),
            )
            await self.telegram_notifier.high_edge_review(
                market_id=top.market_id,
                edge=top.edge,
                confidence=top.confidence,
                reasoning=top.reasoning,
            )
        if flags:
            await self.alert_manager.send("Paper performance degradation", ", ".join(flags))
            await self.telegram_notifier.risk_alert(
                "Paper performance degradation", ", ".join(flags)
            )

    async def _maybe_daily_summary(self) -> None:
        today = utc_now().date()
        if self._last_summary_day == today:
            return
        self._last_summary_day = today
        summary = self.performance_tracker.daily_summary()
        self._append_audit({"event": "daily_summary", "as_of": utc_now().isoformat(), **summary})
        await self.alert_manager.send("Paper daily summary", json.dumps(summary, sort_keys=True))
        await self.telegram_notifier.daily_summary(summary)

    def _equity(self) -> float:
        return self.config.virtual_capital + self._unrealized_pnl()

    def _unrealized_pnl(self) -> float:
        return sum(position.unrealized_pnl for position in self.state.positions.values())

    def _load_state(self) -> PaperTraderState:
        if self.config.state_path.exists():
            payload = json.loads(self.config.state_path.read_text())
            return PaperTraderState.model_validate(payload)
        return PaperTraderState(
            virtual_capital=self.config.virtual_capital,
            cash=self.config.virtual_capital,
            equity=self.config.virtual_capital,
        )

    def _persist_state(self) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.state_path.write_text(self.state.model_dump_json(indent=2))

    def _append_audit(self, payload: dict[str, Any]) -> None:
        self.config.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config.audit_log_path.open("a") as handle:
            handle.write(json.dumps(payload, default=str, sort_keys=True) + "\n")


def config_from_settings(settings: Settings) -> PaperTraderConfig:
    """Build paper-trader config from global settings."""

    return PaperTraderConfig(
        interval_seconds=settings.paper_trader_interval_seconds,
        virtual_capital=settings.paper_trader_virtual_capital_usd,
        min_volume=settings.paper_trader_min_volume_usd,
        max_markets=settings.paper_trader_max_markets,
        review_mode=settings.paper_trader_review_mode,
        review_threshold=settings.paper_trader_review_threshold,
        review_timeout_seconds=settings.paper_trader_review_timeout_seconds,
        review_flag_path=settings.paper_trader_review_flag_path,
        state_path=settings.paper_trader_state_path,
        audit_log_path=settings.paper_trader_audit_log_path,
        use_advanced_features=settings.use_advanced_features,
        llm_provider=settings.llm_provider,
        crypto_only=False,
    )


def _market_volume(market: UnifiedMarket) -> float:
    return float(market.raw.get("volume", market.raw.get("liquidity", 0)) or 0.0)


def _liquidity_by_market(markets: Sequence[UnifiedMarket]) -> dict[str, float]:
    return {
        market.market_id: float(market.raw.get("liquidity", market.raw.get("volume", 0)) or 0.0)
        for market in markets
    }


def _liquidity_market_row(market: UnifiedMarket) -> dict[str, Any]:
    raw = market.raw
    bid = float(raw.get("best_bid", raw.get("bid", 0.0)) or 0.0)
    ask = float(raw.get("best_ask", raw.get("ask", 0.0)) or 0.0)
    market_probability = float(
        raw.get("last_trade_price", raw.get("price", raw.get("mid", 0.5))) or 0.5
    )
    spread = float(raw.get("spread", abs(ask - bid) if ask and bid else 0.03) or 0.03)
    return {
        "market_id": market.market_id,
        "market_probability": market_probability,
        "model_probability": market_probability,
        "spread": spread,
        "liquidity": float(raw.get("liquidity", raw.get("volume", 0.0)) or 0.0),
        "volume": float(raw.get("volume", raw.get("liquidity", 0.0)) or 0.0),
        "duration_hours": float(raw.get("duration_hours", 24.0) or 24.0),
        "category": raw.get("category", "crypto" if infer_asset_symbol(market) else "unknown"),
        "slug": raw.get("slug", market.market_id),
        "url": raw.get("url"),
    }


def _signal_summary(signal: EdgeSignal) -> dict[str, Any]:
    return {
        "market_id": signal.market_id,
        "market_prob": signal.market_prob,
        "model_prob": signal.model_prob,
        "edge": signal.edge,
        "edge_abs": abs(signal.edge),
        "confidence": signal.confidence,
        "reasoning": signal.reasoning,
    }


def _action_from_delta(delta: float, target_notional: float) -> str:
    if target_notional == 0:
        return "close"
    if delta > 0:
        return "increase"
    return "decrease"
