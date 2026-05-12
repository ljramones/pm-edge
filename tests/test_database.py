from sqlmodel import create_engine

from core import UnifiedMarket, Venue
from core.models import MarketStatus
from data.database import HistoricalMarketStore


def test_historical_store_records_resolution() -> None:
    engine = create_engine("sqlite:///:memory:")
    store = HistoricalMarketStore(engine=engine)
    store.init_db()

    market = store.upsert_market(
        UnifiedMarket(
            venue=Venue.POLYMARKET,
            market_id="m-1",
            title="Will it rain tomorrow?",
            outcomes=["Yes", "No"],
        )
    )
    resolution = store.record_resolution(market_id=market.id, winning_outcome="Yes")

    assert resolution.winning_outcome == "Yes"
    assert store.resolved_markets()[0].status == MarketStatus.RESOLVED
