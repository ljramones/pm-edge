from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pyarrow.parquet as pq
import pytest

from data.forward_indexer import BookState, BufferedParquetWriter, MarketDescriptor, TableName
from data.forward_indexer.base import VenueIndexer, VenueStats
from data.forward_indexer.filters import (
    ActivityThresholds,
    activity_filter_rejection_reason,
    empty_rejection_counts,
    market_passes_activity_filter,
)
from data.forward_indexer.kalshi import KalshiIndexer
from data.forward_indexer.polymarket import PolymarketIndexer
from data.forward_indexer.runner import (
    IndexerRunner,
    RunnerConfig,
    current_memory_mb,
    ranked_markets,
)
from data.forward_indexer.schemas import (
    SCHEMA_VERSION,
    market_metadata_snapshot_schema,
    order_book_snapshot_schema,
    trade_event_schema,
)


def test_forward_indexer_schemas_include_version() -> None:
    assert order_book_snapshot_schema().field("schema_version").type.bit_width == 16
    assert trade_event_schema().field("schema_version").type.bit_width == 16
    assert market_metadata_snapshot_schema().field("schema_version").type.bit_width == 16


def test_partition_path_generation(tmp_path: Path) -> None:
    writer = BufferedParquetWriter(tmp_path)
    path = writer.partition_dir(
        TableName.ORDER_BOOK_SNAPSHOTS,
        venue="polymarket",
        timestamp=datetime(2026, 5, 13, tzinfo=UTC),
    )

    assert path == tmp_path / "order_book_snapshots" / "venue=polymarket" / "date=2026-05-13"


@pytest.mark.asyncio
async def test_deduplication_on_resume(tmp_path: Path) -> None:
    writer = BufferedParquetWriter(tmp_path, flush_max_records=1)
    record = {
        "schema_version": SCHEMA_VERSION,
        "venue": "polymarket",
        "market_id": "m1",
        "token_id_yes": "yes",
        "token_id_no": "no",
        "timestamp_utc": datetime(2026, 5, 13, 12, tzinfo=UTC),
        "bid_levels": [{"price": 0.49, "size": 10.0}],
        "ask_levels": [{"price": 0.51, "size": 10.0}],
        "top_bid": 0.49,
        "top_ask": 0.51,
        "mid": 0.5,
        "spread": 0.02,
        "snapshot_source": "rest",
    }
    assert await writer.add_records(TableName.ORDER_BOOK_SNAPSHOTS, [record]) == 1
    await writer.flush()

    resumed = BufferedParquetWriter(tmp_path, flush_max_records=1)
    await resumed.load_existing_keys_for_today(current_date=datetime(2026, 5, 13).date())
    assert await resumed.add_records(TableName.ORDER_BOOK_SNAPSHOTS, [record]) == 0

    files = await asyncio.to_thread(lambda: list(Path(tmp_path).rglob("*.parquet")))
    assert len(files) == 1
    assert pq.ParquetFile(files[0]).metadata.num_rows == 1


@pytest.mark.asyncio
async def test_book_state_diff_application() -> None:
    state = BookState(venue="polymarket", market_id="m1", token_id_yes="yes", token_id_no="no")
    await state.replace(
        bids=[{"price": 0.48, "size": 4}, {"price": 0.47, "size": 5}],
        asks=[{"price": 0.52, "size": 6}],
    )
    await state.apply_diff(side="bid", price=0.49, size=3)
    await state.apply_diff(side="ask", price=0.52, size=0)
    snapshot = await state.snapshot(timestamp=datetime(2026, 5, 13, tzinfo=UTC))

    assert snapshot["top_bid"] == 0.49
    assert snapshot["top_ask"] is None
    assert snapshot["bid_levels"] == [
        {"price": 0.49, "size": 3.0},
        {"price": 0.48, "size": 4.0},
        {"price": 0.47, "size": 5.0},
    ]


def test_activity_filter_rejects_high_volume_wide_spread() -> None:
    now = datetime(2026, 5, 13, 12, tzinfo=UTC)

    assert not market_passes_activity_filter(
        volume_24h=20_000,
        spread=0.30,
        last_trade_at=now - timedelta(hours=1),
        created_at=now - timedelta(hours=2),
        end_date=now + timedelta(hours=4),
        thresholds=ActivityThresholds(),
        now=now,
    )


def test_activity_filter_fails_closed_on_missing_volume() -> None:
    now = datetime(2026, 5, 13, 12, tzinfo=UTC)

    assert not market_passes_activity_filter(
        volume_24h=None,
        spread=0.05,
        last_trade_at=now - timedelta(hours=1),
        created_at=now - timedelta(hours=2),
        end_date=now + timedelta(hours=4),
        thresholds=ActivityThresholds(),
        now=now,
    )


def test_activity_filter_rejects_stale_last_trade() -> None:
    now = datetime(2026, 5, 13, 12, tzinfo=UTC)

    assert not market_passes_activity_filter(
        volume_24h=20_000,
        spread=0.05,
        last_trade_at=now - timedelta(hours=48),
        created_at=now - timedelta(hours=2),
        end_date=now + timedelta(hours=4),
        thresholds=ActivityThresholds(max_last_trade_age_hours=24),
        now=now,
    )


def test_activity_filter_allows_missing_created_at() -> None:
    now = datetime(2026, 5, 13, 12, tzinfo=UTC)

    assert market_passes_activity_filter(
        volume_24h=20_000,
        spread=0.05,
        last_trade_at=now - timedelta(hours=1),
        created_at=None,
        end_date=now + timedelta(hours=4),
        thresholds=ActivityThresholds(),
        now=now,
    )


def test_activity_filter_rejection_reason_counts_first_failure() -> None:
    now = datetime(2026, 5, 13, 12, tzinfo=UTC)
    markets = [
        MarketDescriptor(
            venue="test",
            market_id="low-volume",
            question="Low volume",
            volume_24h=1_000,
            spread=0.30,
            last_trade_at=now - timedelta(hours=48),
        ),
        MarketDescriptor(
            venue="test",
            market_id="wide-spread",
            question="Wide spread",
            volume_24h=20_000,
            spread=0.30,
            last_trade_at=now - timedelta(hours=1),
        ),
        MarketDescriptor(
            venue="test",
            market_id="stale",
            question="Stale",
            volume_24h=20_000,
            spread=0.05,
            last_trade_at=now - timedelta(hours=48),
        ),
        MarketDescriptor(
            venue="test",
            market_id="too-new",
            question="Too new",
            volume_24h=20_000,
            spread=0.05,
            last_trade_at=now - timedelta(hours=1),
            created_at=now - timedelta(minutes=5),
        ),
        MarketDescriptor(
            venue="test",
            market_id="too-close",
            question="Too close",
            volume_24h=20_000,
            spread=0.05,
            last_trade_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=2),
            end_date=now + timedelta(hours=1),
        ),
        MarketDescriptor(
            venue="test",
            market_id="pass",
            question="Pass",
            volume_24h=20_000,
            spread=0.05,
            last_trade_at=now - timedelta(hours=1),
            created_at=None,
            end_date=now + timedelta(hours=4),
        ),
    ]
    counts = empty_rejection_counts()
    passed = 0

    for market in markets:
        reason = activity_filter_rejection_reason(
            volume_24h=market.volume_24h,
            spread=market.spread,
            last_trade_at=market.last_trade_at,
            created_at=market.created_at,
            end_date=market.end_date,
            thresholds=ActivityThresholds(),
            now=now,
        )
        if reason is None:
            passed += 1
        else:
            counts[reason] += 1

    assert passed == 1
    assert counts == {
        "rejected_low_volume": 1,
        "rejected_wide_spread": 1,
        "rejected_stale_trade": 1,
        "rejected_too_new": 1,
        "rejected_too_close_to_end": 1,
    }


def test_ranked_markets_prefers_higher_volume_then_liquidity_then_tighter_spread() -> None:
    markets = [
        MarketDescriptor(
            venue="test",
            market_id="low",
            question="Low",
            volume_24h=15_000,
            liquidity=5_000,
            spread=0.01,
        ),
        MarketDescriptor(
            venue="test",
            market_id="wide",
            question="Wide",
            volume_24h=20_000,
            liquidity=5_000,
            spread=0.09,
        ),
        MarketDescriptor(
            venue="test",
            market_id="tight",
            question="Tight",
            volume_24h=20_000,
            liquidity=5_000,
            spread=0.01,
        ),
    ]

    assert [market.market_id for market in ranked_markets(markets)] == ["tight", "wide", "low"]


def test_current_memory_mb_uses_current_rss_from_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "data.forward_indexer.runner.subprocess.check_output",
        lambda *_args, **_kwargs: "204800\n",
    )

    assert current_memory_mb() == 200.0


@pytest.mark.asyncio
async def test_websocket_mock_dropout_reconnect_updates_book_state() -> None:
    market = MarketDescriptor(
        venue="polymarket",
        market_id="m1",
        question="Test",
        token_id_yes="yes-token",
        token_id_no="no-token",
        volume_24h=10_000,
    )
    client = MockAsyncClient()
    ws_factory = DropoutWsFactory()
    indexer = PolymarketIndexer(
        base_url="https://clob.polymarket.com",
        client=client,
        ws_connect=ws_factory.connect,
    )

    task = asyncio.create_task(indexer.subscribe_books([market]))
    await asyncio.sleep(1.2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    state = await indexer.current_book_state("m1")
    assert state is not None
    snapshot = await state.snapshot()
    assert snapshot["top_bid"] in {0.5, 0.51}
    assert ws_factory.connection_count >= 1


@pytest.mark.asyncio
async def test_polymarket_discovery_uses_gamma_active_filter() -> None:
    client = RecordingAsyncClient(
        [
            {
                "markets": [
                    {
                        "id": "gamma-market-1",
                        "question": "Will BTC close above 100k?",
                        "conditionId": "condition-1",
                        "active": True,
                        "closed": False,
                        "clobTokenIds": '["yes-token", "no-token"]',
                        "volumeNum": "2500",
                        "liquidityNum": "500",
                    }
                ],
                "next_cursor": None,
            }
        ]
    )
    indexer = PolymarketIndexer(
        base_url="https://clob.polymarket.com",
        gamma_url="https://gamma-api.polymarket.com",
        client=client,
    )

    markets = await indexer.discover_markets()

    assert markets[0].market_id == "condition-1"
    assert markets[0].token_id_yes == "yes-token"
    assert markets[0].token_id_no == "no-token"
    assert client.requests[0]["url"].startswith("https://gamma-api.polymarket.com/markets")
    assert client.requests[0]["params"]["closed"] == "false"
    assert client.requests[0]["params"]["active"] == "true"
    assert client.requests[0]["params"]["volume_num_min"] == "10000.0"


@pytest.mark.asyncio
async def test_polymarket_discovery_retries_transient_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("data.forward_indexer.polymarket.asyncio.sleep", fast_sleep)
    client = FlakyRecordingAsyncClient(
        [
            {
                "markets": [
                    {
                        "id": "gamma-market-1",
                        "question": "Will BTC close above 100k?",
                        "conditionId": "condition-1",
                        "active": True,
                        "closed": False,
                        "clobTokenIds": '["yes-token", "no-token"]',
                        "volumeNum": "2500",
                    }
                ],
                "next_cursor": None,
            }
        ]
    )
    indexer = PolymarketIndexer(
        base_url="https://clob.polymarket.com",
        gamma_url="https://gamma-api.polymarket.com",
        client=client,
    )

    markets = await indexer.discover_markets()

    assert markets[0].market_id == "condition-1"
    assert len(client.requests) == 2
    assert indexer.stats().errors_since_heartbeat == 1


@pytest.mark.asyncio
async def test_polymarket_book_refresh_skips_stale_token_404() -> None:
    market = MarketDescriptor(
        venue="polymarket",
        market_id="m1",
        question="Test",
        token_id_yes="stale-token",
        token_id_no="no-token",
    )
    indexer = PolymarketIndexer(
        base_url="https://clob.polymarket.com",
        client=StatusCodeAsyncClient(status_code=404),
    )

    await indexer.refresh_book(market)

    assert await indexer.current_book_state("m1") is None
    assert indexer.stats().errors_since_heartbeat == 1


@pytest.mark.asyncio
async def test_kalshi_discovery_includes_open_status_filter() -> None:
    client = RecordingAsyncClient(
        [
            {
                "markets": [
                    {
                        "ticker": "KXBTC",
                        "title": "Bitcoin market",
                        "status": "open",
                        "volume_24h": 2500,
                    }
                ],
                "cursor": "",
            }
        ]
    )
    indexer = KalshiIndexer(
        base_url="https://external-api.kalshi.com/trade-api/v2",
        client=client,
    )

    markets = await indexer.discover_markets()

    assert markets[0].market_id == "KXBTC"
    assert client.requests[0]["url"] == "https://external-api.kalshi.com/trade-api/v2/markets"
    assert client.requests[0]["params"]["status"] == "open"
    assert client.requests[0]["params"]["limit"] == "1000"


@pytest.mark.asyncio
async def test_kalshi_discovery_paces_successful_rest_requests() -> None:
    client = RecordingAsyncClient(
        [
            {
                "markets": [
                    {
                        "ticker": "KXBTC",
                        "title": "Bitcoin market",
                        "status": "open",
                    }
                ],
                "cursor": "",
            }
        ]
    )
    indexer = KalshiIndexer(
        base_url="https://external-api.kalshi.com/trade-api/v2",
        client=client,
        request_delay_seconds=0.1,
    )

    started = time.perf_counter()
    await indexer.discover_markets()
    elapsed = time.perf_counter() - started

    assert 0.05 <= elapsed < 0.5


@pytest.mark.asyncio
async def test_forward_index_dry_run_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scripts.forward_index as cli

    class Settings:
        log_level = "INFO"
        log_json = False
        forward_indexer_emit_cadence_seconds = 15
        forward_indexer_discovery_cadence_seconds = 300
        forward_indexer_book_depth_levels = 5
        forward_indexer_min_24h_volume_usd = 1_000.0
        forward_indexer_max_spread_cents = 20.0
        forward_indexer_max_last_trade_age_hours = 24.0
        forward_indexer_min_market_age_minutes = 30.0
        forward_indexer_min_time_to_close_hours = 2.0
        forward_indexer_max_tracked_markets_per_venue = 500
        forward_indexer_output_dir = tmp_path
        forward_indexer_max_memory_mb = 1024
        http_timeout_seconds = 1
        polymarket_base_url = "https://clob.polymarket.com"
        kalshi_base_url = "https://external-api.kalshi.com/trade-api/v2"
        kalshi_request_delay_seconds = 0.0

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(sys, "argv", ["forward_index.py", "--dry-run", "--venues", "polymarket"])
    monkeypatch.setattr(cli, "PolymarketIndexer", FakeVenueFactory)
    await cli.run()


@pytest.mark.asyncio
async def test_discover_once_runs_venue_discovery_concurrently(tmp_path: Path) -> None:
    indexers: list[VenueIndexer] = [
        SlowDiscoverIndexer(venue="polymarket", delay_seconds=0.5),
        SlowDiscoverIndexer(venue="kalshi", delay_seconds=0.5),
    ]
    runner = IndexerRunner(
        config=RunnerConfig(output_dir=tmp_path, dry_run=True),
        indexers=indexers,
        writer=BufferedParquetWriter(tmp_path),
    )

    started = time.perf_counter()
    await runner.discover_once()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.8
    assert set(runner._tracked_markets) == {"polymarket", "kalshi"}


@pytest.mark.asyncio
async def test_runner_stop_interrupts_long_sleep(tmp_path: Path) -> None:
    runner = IndexerRunner(
        config=RunnerConfig(
            output_dir=tmp_path,
            discovery_cadence_seconds=60,
            emit_cadence_seconds=60,
            heartbeat_seconds=60,
        ),
        indexers=[SlowDiscoverIndexer(venue="polymarket", delay_seconds=0.0)],
        writer=BufferedParquetWriter(tmp_path),
    )

    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.1)
    await runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert task.done()


class MockAsyncClient:
    async def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        request = httpx.Request("GET", url)
        if url.endswith("/book"):
            return httpx.Response(
                200,
                json={
                    "bids": [{"price": "0.49", "size": "10"}],
                    "asks": [{"price": "0.52", "size": "8"}],
                },
                request=request,
            )
        return httpx.Response(200, json={"data": [], "next_cursor": None}, request=request)


class RecordingAsyncClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.requests: list[dict[str, Any]] = []

    async def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        self.requests.append({"url": url, "params": params or {}})
        request = httpx.Request("GET", url)
        payload = self.payloads.pop(0) if self.payloads else {}
        return httpx.Response(200, json=payload, request=request)


class FlakyRecordingAsyncClient(RecordingAsyncClient):
    async def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        self.requests.append({"url": url, "params": params or {}})
        if len(self.requests) == 1:
            raise httpx.ReadTimeout("timed out")
        request = httpx.Request("GET", url)
        payload = self.payloads.pop(0) if self.payloads else {}
        return httpx.Response(200, json=payload, request=request)


class StatusCodeAsyncClient:
    def __init__(self, *, status_code: int) -> None:
        self.status_code = status_code

    async def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(self.status_code, json={}, request=request)


class FakeWs:
    def __init__(self, messages: list[str], *, fail_after: bool) -> None:
        self.messages = messages
        self.fail_after = fail_after
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self) -> FakeWs:
        return self

    async def __anext__(self) -> str:
        if self.messages:
            return self.messages.pop(0)
        if self.fail_after:
            raise ConnectionError("dropout")
        await asyncio.sleep(1)
        raise StopAsyncIteration


class DropoutWsFactory:
    def __init__(self) -> None:
        self.connection_count = 0

    async def connect(self, _url: str) -> FakeWs:
        self.connection_count += 1
        message = (
            '{"event_type":"price_change","asset_id":"yes-token",'
            '"changes":[{"side":"bid","price":"0.50","size":"5"}]}'
        )
        return FakeWs([message], fail_after=self.connection_count == 1)


class FakeVenueFactory(VenueIndexer):
    venue = "polymarket"

    def __init__(self, **_kwargs: Any) -> None:
        self._stats = VenueStats(venue=self.venue)

    async def discover_markets(self) -> list[MarketDescriptor]:
        return [
            MarketDescriptor(
                venue=self.venue,
                market_id="m1",
                question="Test",
                volume_24h=2_000,
                spread=0.1,
            )
        ]

    async def subscribe_books(self, markets: list[MarketDescriptor]) -> None:
        raise AssertionError("dry-run should not subscribe")

    async def subscribe_trades(self, markets: list[MarketDescriptor]) -> None:
        raise AssertionError("dry-run should not subscribe")

    async def current_book_state(self, market_id: str) -> BookState | None:
        return None

    async def flush_pending(self) -> None:
        return None

    def stats(self) -> VenueStats:
        return self._stats


class SlowDiscoverIndexer(VenueIndexer):
    def __init__(self, *, venue: str, delay_seconds: float) -> None:
        self.venue = venue
        self.delay_seconds = delay_seconds
        self._stats = VenueStats(venue=venue)

    async def discover_markets(self) -> list[MarketDescriptor]:
        await asyncio.sleep(self.delay_seconds)
        return [
            MarketDescriptor(
                venue=self.venue,
                market_id=f"{self.venue}-m1",
                question="Test",
                volume_24h=2_000,
                spread=0.1,
            )
        ]

    async def subscribe_books(self, markets: list[MarketDescriptor]) -> None:
        await asyncio.Event().wait()

    async def subscribe_trades(self, markets: list[MarketDescriptor]) -> None:
        await asyncio.Event().wait()

    async def current_book_state(self, market_id: str) -> BookState | None:
        return None

    async def flush_pending(self) -> None:
        return None

    def stats(self) -> VenueStats:
        return self._stats
