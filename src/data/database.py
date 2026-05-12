"""Persistence helpers for Phase 0 market history."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from core.client import UnifiedMarket
from core.config import Settings, get_settings
from core.models import Market, MarketPrice, MarketStatus, Resolution, Venue, utc_now


class HistoricalMarketStore:
    """Small SQLModel repository for markets, prices, and resolutions."""

    def __init__(self, engine: Engine | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.engine = engine or create_engine(self.settings.database_url)

    def init_db(self) -> None:
        """Create database tables if they do not already exist."""

        SQLModel.metadata.create_all(self.engine)

    def upsert_market(self, market: UnifiedMarket, *, session: Session | None = None) -> Market:
        """Insert or update a unified market by venue and venue market id."""

        owns_session = session is None
        active_session = session or Session(self.engine)
        try:
            existing = active_session.exec(
                select(Market).where(
                    Market.venue == Venue(market.venue.value),
                    Market.venue_market_id == market.market_id,
                )
            ).first()

            if existing is None:
                existing = Market(
                    venue=Venue(market.venue.value),
                    venue_market_id=market.market_id,
                    title=market.title,
                )
                active_session.add(existing)

            existing.title = market.title
            existing.url = market.url
            existing.outcomes = market.outcomes
            existing.status = _coerce_market_status(market.status)
            existing.closes_at = _parse_datetime(market.closes_at)
            existing.raw = market.raw
            existing.updated_at = utc_now()

            if owns_session:
                active_session.commit()
                active_session.refresh(existing)
            return existing
        finally:
            if owns_session:
                active_session.close()

    def upsert_markets(self, markets: Iterable[UnifiedMarket]) -> list[Market]:
        """Insert or update a batch of markets in one transaction."""

        with Session(self.engine) as session:
            saved = [self.upsert_market(market, session=session) for market in markets]
            session.commit()
            for market in saved:
                session.refresh(market)
            return saved

    def record_price(
        self,
        *,
        market_id: str,
        outcome: str,
        bid: Decimal | None = None,
        ask: Decimal | None = None,
        last: Decimal | None = None,
        volume: Decimal | None = None,
        liquidity: Decimal | None = None,
        observed_at: datetime | None = None,
        raw: dict[str, object] | None = None,
    ) -> MarketPrice:
        """Record a historical price snapshot."""

        mid = None
        if bid is not None and ask is not None:
            mid = (bid + ask) / Decimal("2")

        price = MarketPrice(
            market_id=market_id,
            outcome=outcome,
            bid=bid,
            ask=ask,
            mid=mid,
            last=last,
            volume=volume,
            liquidity=liquidity,
            observed_at=observed_at or utc_now(),
            raw=raw or {},
        )
        with Session(self.engine) as session:
            session.add(price)
            session.commit()
            session.refresh(price)
            return price

    def record_resolution(
        self,
        *,
        market_id: str,
        winning_outcome: str,
        resolved_at: datetime | None = None,
        source_url: str | None = None,
        notes: str | None = None,
        raw: dict[str, object] | None = None,
    ) -> Resolution:
        """Record final outcome and mark the market resolved."""

        resolved_time = resolved_at or utc_now()
        resolution = Resolution(
            market_id=market_id,
            winning_outcome=winning_outcome,
            resolved_at=resolved_time,
            source_url=source_url,
            notes=notes,
            raw=raw or {},
        )
        with Session(self.engine) as session:
            market = session.get(Market, market_id)
            if market is not None:
                market.status = MarketStatus.RESOLVED
                market.resolved_at = resolved_time
                market.updated_at = utc_now()
                session.add(market)
            session.add(resolution)
            session.commit()
            session.refresh(resolution)
            return resolution

    def resolved_markets(self, *, limit: int = 1000) -> list[Market]:
        """Return resolved markets for backfills and training datasets."""

        with Session(self.engine) as session:
            return list(
                session.exec(
                    select(Market)
                    .where(Market.status == MarketStatus.RESOLVED)
                    .order_by(Market.resolved_at.desc())  # type: ignore[union-attr]
                    .limit(limit)
                )
            )


def _coerce_market_status(status: str | None) -> MarketStatus:
    if not status:
        return MarketStatus.OPEN
    normalized = status.lower()
    if normalized in {"closed", "inactive"}:
        return MarketStatus.CLOSED
    if normalized in {"resolved", "final"}:
        return MarketStatus.RESOLVED
    if normalized in {"cancelled", "canceled"}:
        return MarketStatus.CANCELLED
    return MarketStatus.OPEN


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
