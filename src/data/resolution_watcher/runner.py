"""Resolution watcher polling runner."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeVar

import duckdb

from utils.logging import configure_logging, get_logger

from .kalshi import KalshiResolutionClient
from .persistence import ResolutionOutcomeWriter
from .polymarket import PolymarketResolutionClient
from .schema import FinalBookSnapshot, MarketResolutionCandidate, ResolvedMarketOutcome
from .settings import ResolutionWatcherSettings


class ResolutionClient(Protocol):
    venue: str

    async def fetch_resolution_outcome(
        self,
        candidate: MarketResolutionCandidate,
        *,
        detected_at: datetime,
        final_snapshot: FinalBookSnapshot,
    ) -> ResolvedMarketOutcome | None: ...

    async def close(self) -> None: ...


class ResolutionWatcherRunner:
    """Poll local metadata snapshots and venue APIs for newly resolved markets."""

    def __init__(
        self,
        *,
        settings: ResolutionWatcherSettings,
        clients: dict[str, ResolutionClient] | None = None,
        writer: ResolutionOutcomeWriter | None = None,
    ) -> None:
        self.settings = settings
        self.clients = clients or {
            "polymarket": PolymarketResolutionClient(
                base_url=settings.polymarket_base_url,
                timeout_seconds=settings.http_timeout_seconds,
                retry_attempts=settings.retry_attempts,
            ),
            "kalshi": KalshiResolutionClient(
                base_url=settings.kalshi_base_url,
                timeout_seconds=settings.http_timeout_seconds,
                retry_attempts=settings.retry_attempts,
            ),
        }
        self.writer = writer or ResolutionOutcomeWriter(settings.output_dir)
        self.seen_resolutions: set[tuple[str, str]] = set()
        self.total_resolved_since_start = 0
        self.markets_checked_since_heartbeat = 0
        self.resolved_since_heartbeat = 0
        self._logger = get_logger(__name__)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        self._install_signal_handlers()
        while not self._stop.is_set():
            started = datetime.now(tz=UTC)
            await self.run_once()
            await self._emit_heartbeat()
            elapsed = (datetime.now(tz=UTC) - started).total_seconds()
            sleep_time = max(0.0, self.settings.poll_cadence_seconds - elapsed)
            if await self._sleep_or_stop(sleep_time):
                break

    async def stop(self) -> None:
        self._stop.set()
        await asyncio.gather(*(client.close() for client in self.clients.values()))

    async def run_once(self) -> None:
        detected_at = datetime.now(tz=UTC)
        for venue in self.settings.venues_enabled:
            client = self.clients.get(venue)
            if client is None:
                self._logger.warning("resolution_watcher_venue_disabled", venue=venue)
                continue
            try:
                candidates = detect_resolution_candidates(
                    self.settings.source_dir,
                    venue=venue,
                    seen=self.seen_resolutions,
                    now=detected_at,
                )
                self.markets_checked_since_heartbeat += len(candidates)
                written: list[ResolvedMarketOutcome] = []
                for candidate in candidates:
                    final_snapshot = find_final_book_snapshot(
                        self.settings.source_dir,
                        venue=venue,
                        market_id=candidate.market_id,
                        before=detected_at,
                    )
                    if self.settings.dry_run:
                        continue
                    outcome = await client.fetch_resolution_outcome(
                        candidate,
                        detected_at=detected_at,
                        final_snapshot=final_snapshot,
                    )
                    if outcome is None:
                        continue
                    written.append(outcome)
                    self.seen_resolutions.add((venue, candidate.market_id))
                if written:
                    accepted = await self.writer.write(written)
                    self.total_resolved_since_start += accepted
                    self.resolved_since_heartbeat += accepted
                self._logger.info(
                    "resolution_watcher_cycle",
                    venue=venue,
                    markets_checked=len(candidates),
                    markets_resolved_this_cycle=len(written),
                    total_resolved_since_start=self.total_resolved_since_start,
                    dry_run=self.settings.dry_run,
                )
            except Exception:
                self._logger.exception("resolution_watcher_venue_error", venue=venue)

    async def _emit_heartbeat(self) -> None:
        self._logger.info(
            "resolution_watcher_heartbeat",
            markets_checked=self.markets_checked_since_heartbeat,
            markets_resolved_this_cycle=self.resolved_since_heartbeat,
            total_resolved_since_start=self.total_resolved_since_start,
        )
        self.markets_checked_since_heartbeat = 0
        self.resolved_since_heartbeat = 0

    async def _sleep_or_stop(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except TimeoutError:
            return False

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))


def detect_resolution_candidates(
    source_dir: Path,
    *,
    venue: str,
    seen: set[tuple[str, str]],
    now: datetime,
) -> list[MarketResolutionCandidate]:
    metadata_dir = source_dir / "market_metadata_snapshots"
    if not metadata_dir.exists() or not any(metadata_dir.rglob("*.parquet")):
        return []
    con = duckdb.connect()
    try:
        path = _sql_string(str(metadata_dir / "**" / "*.parquet"))
        rows = con.execute(
            f"""
            WITH latest AS (
                SELECT
                    venue,
                    market_id,
                    captured_at_utc::VARCHAR AS captured_at_text,
                    end_date::VARCHAR AS end_date_text,
                    status,
                    raw_json,
                    row_number() OVER (
                        PARTITION BY venue, market_id
                        ORDER BY captured_at_utc DESC
                    ) AS rn
                FROM read_parquet({path})
                WHERE venue = ?
            )
            SELECT venue, market_id, captured_at_text, end_date_text, status, raw_json
            FROM latest
            WHERE rn = 1
              AND (
                end_date_text IS NULL
                OR CAST(end_date_text AS TIMESTAMPTZ) <= CAST(? AS TIMESTAMPTZ)
              )
              AND (
                lower(coalesce(status, '')) IN ('closed', 'settled', 'resolved')
                OR lower(coalesce(json_extract_string(raw_json, '$.closed'), '')) = 'true'
                OR lower(coalesce(json_extract_string(raw_json, '$.status'), '')) IN (
                    'closed', 'settled', 'resolved'
                )
              )
            """,
            [venue, _to_utc(now).isoformat()],
        ).fetchall()
    finally:
        con.close()
    candidates = [
        MarketResolutionCandidate(
            venue=str(row[0]),
            market_id=str(row[1]),
            captured_at_utc=_parse_datetime(row[2]),
            end_date=None if row[3] is None else _parse_datetime(row[3]),
            status=None if row[4] is None else str(row[4]),
            raw_json=None if row[5] is None else str(row[5]),
        )
        for row in rows
        if (str(row[0]), str(row[1])) not in seen
    ]
    return candidates


def find_final_book_snapshot(
    source_dir: Path,
    *,
    venue: str,
    market_id: str,
    before: datetime,
) -> FinalBookSnapshot:
    snapshot_dir = source_dir / "order_book_snapshots" / f"venue={venue}"
    if not snapshot_dir.exists():
        return FinalBookSnapshot(None, None, None, None)
    con = duckdb.connect()
    best: tuple[str | None, float | None, float | None, float | None] | None = None
    try:
        for chunk in _chunks(sorted(snapshot_dir.glob("date=*/*.parquet")), 128):
            if not chunk:
                continue
            path_list = "[" + ", ".join(_sql_string(str(path)) for path in chunk) + "]"
            row = con.execute(
                f"""
                SELECT
                    timestamp_utc::VARCHAR,
                    top_bid,
                    top_ask,
                    spread
                FROM read_parquet({path_list})
                WHERE market_id = ?
                  AND timestamp_utc <= CAST(? AS TIMESTAMPTZ)
                ORDER BY timestamp_utc DESC
                LIMIT 1
                """,
                [market_id, _to_utc(before).isoformat()],
            ).fetchone()
            if row is None:
                continue
            if best is None or _parse_datetime(row[0]) > _parse_datetime(best[0]):
                best = row
    finally:
        con.close()
    if best is None:
        return FinalBookSnapshot(None, None, None, None)
    return FinalBookSnapshot(
        top_bid=None if best[1] is None else float(best[1]),
        top_ask=None if best[2] is None else float(best[2]),
        spread=None if best[3] is None else float(best[3]),
        timestamp_utc=_parse_datetime(best[0]),
    )


async def main_loop(settings: ResolutionWatcherSettings) -> None:
    """Run the resolution watcher until stopped."""

    await ResolutionWatcherRunner(settings=settings).run()


def main() -> int:
    settings = ResolutionWatcherSettings()
    configure_logging()
    asyncio.run(main_loop(settings))
    return 0


T = TypeVar("T")


def _chunks(items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _parse_datetime(value: object) -> datetime:
    text = str(value).replace(" ", "T").replace("Z", "+00:00")
    if text.endswith("-00"):
        text = text[:-3] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return _to_utc(parsed)


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
