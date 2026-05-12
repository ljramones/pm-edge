from datetime import UTC, datetime

import pytest

from core import UnifiedMarket, Venue
from data.onchain_processor import OnChainProcessor, infer_asset_symbol


def test_infer_asset_symbol_from_market_title() -> None:
    market = UnifiedMarket(
        venue=Venue.POLYMARKET,
        market_id="m-1",
        title="Will ETH trade above 4000 by June?",
    )

    assert infer_asset_symbol(market) == "ETH"


@pytest.mark.asyncio
async def test_onchain_processor_returns_none_for_non_crypto_market() -> None:
    processor = OnChainProcessor()
    market = UnifiedMarket(
        venue=Venue.KALSHI,
        market_id="m-2",
        title="Will unemployment rise?",
    )

    snapshot = await processor.fetch_market_metrics(market, as_of=datetime(2026, 5, 12, tzinfo=UTC))
    await processor.close()

    assert snapshot is None
