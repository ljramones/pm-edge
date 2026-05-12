from decimal import Decimal

from core import Venue
from core.scanner import MarketSnapshot, detect_cross_venue_arbitrage


def test_detect_cross_venue_arbitrage() -> None:
    snapshots = [
        MarketSnapshot(
            venue=Venue.POLYMARKET,
            market_id="poly-1",
            title="Will candidate A win?",
            outcome="Yes",
            best_bid=Decimal("0.51"),
            best_ask=Decimal("0.52"),
            ask_size=Decimal("100"),
        ),
        MarketSnapshot(
            venue=Venue.KALSHI,
            market_id="kalshi-1",
            title="Will candidate A win?",
            outcome="Yes",
            best_bid=Decimal("0.56"),
            best_ask=Decimal("0.58"),
            bid_size=Decimal("20"),
        ),
    ]

    opportunities = detect_cross_venue_arbitrage(snapshots, min_edge_bps=Decimal("25"))

    assert len(opportunities) == 1
    assert opportunities[0].buy_venue == Venue.POLYMARKET
    assert opportunities[0].sell_venue == Venue.KALSHI
    assert opportunities[0].edge == Decimal("0.04")
    assert opportunities[0].max_size == Decimal("20")
