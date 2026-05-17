"""Resolution watcher polling runner."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
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
        self.metadata_candidates_since_heartbeat = 0
        self.new_resolutions_since_heartbeat = 0
        self.api_fallbacks_since_heartbeat = 0
        self.disappeared_candidates_since_heartbeat = 0
        self.disappeared_resolutions_since_heartbeat = 0
        self.disappeared_skipped_as_still_active_since_heartbeat = 0
        self._logger = get_logger(__name__)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        self._install_signal_handlers()
        self.seen_resolutions.update(load_seen_resolutions(self.settings.output_dir))
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
                detection = detect_resolution_candidates(
                    self.settings.source_dir,
                    venue=venue,
                    seen=self.seen_resolutions,
                    now=detected_at,
                    lookback_days=self.settings.metadata_lookback_days,
                )
                candidates = detection.candidates
                self.metadata_candidates_since_heartbeat += detection.metadata_candidates_seen
                self.new_resolutions_since_heartbeat += len(candidates)
                self.markets_checked_since_heartbeat += len(candidates)
                written: list[ResolvedMarketOutcome] = []
                api_fallbacks_used = 0
                for candidate in candidates:
                    snapshot_anchor = candidate.resolution_timestamp_utc or detected_at
                    final_snapshot = find_final_book_snapshot(
                        self.settings.source_dir,
                        venue=venue,
                        market_id=candidate.market_id,
                        before=snapshot_anchor,
                    )
                    if self.settings.dry_run:
                        continue
                    outcome = _outcome_from_metadata(
                        candidate,
                        detected_at=detected_at,
                        final_snapshot=final_snapshot,
                    )
                    if outcome is None:
                        api_fallbacks_used += 1
                        self.api_fallbacks_since_heartbeat += 1
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
                disappeared_written = await self._process_disappeared_candidates(
                    venue=venue,
                    client=client,
                    detected_at=detected_at,
                )
                self._logger.info(
                    "resolution_watcher_cycle",
                    venue=venue,
                    markets_checked=len(candidates) + disappeared_written.markets_checked,
                    metadata_candidates_seen=detection.metadata_candidates_seen,
                    new_resolutions_detected=len(candidates),
                    api_fallbacks_used=api_fallbacks_used,
                    disappeared_candidates_seen=disappeared_written.candidates_seen,
                    disappeared_skipped_as_still_active=(
                        disappeared_written.skipped_as_still_active
                    ),
                    disappeared_resolutions_detected=disappeared_written.resolutions_detected,
                    markets_resolved_this_cycle=(
                        len(written) + disappeared_written.resolutions_detected
                    ),
                    total_resolved_since_start=self.total_resolved_since_start,
                    dry_run=self.settings.dry_run,
                )
            except Exception:
                self._logger.exception("resolution_watcher_venue_error", venue=venue)

    async def _process_disappeared_candidates(
        self,
        *,
        venue: str,
        client: ResolutionClient,
        detected_at: datetime,
    ) -> DisappearedProcessingResult:
        detection = detect_disappeared_candidates(
            self.settings.source_dir,
            venue=venue,
            seen=self.seen_resolutions,
            now=detected_at,
            lookback_hours=self.settings.disappeared_lookback_hours,
            max_candidates=self.settings.disappeared_max_checks_per_cycle,
        )
        self.disappeared_candidates_since_heartbeat += detection.disappeared_candidates_seen
        self.disappeared_skipped_as_still_active_since_heartbeat += (
            detection.disappeared_skipped_as_still_active
        )
        self.markets_checked_since_heartbeat += len(detection.candidates)
        if self.settings.dry_run:
            return DisappearedProcessingResult(
                candidates_seen=detection.disappeared_candidates_seen,
                skipped_as_still_active=detection.disappeared_skipped_as_still_active,
                markets_checked=len(detection.candidates),
                resolutions_detected=0,
            )
        written: list[ResolvedMarketOutcome] = []
        for candidate in detection.candidates:
            final_snapshot = find_final_book_snapshot(
                self.settings.source_dir,
                venue=venue,
                market_id=candidate.market_id,
                before=detected_at,
            )
            outcome = await client.fetch_resolution_outcome(
                candidate,
                detected_at=detected_at,
                final_snapshot=final_snapshot,
            )
            if outcome is None:
                continue
            written.append(replace(outcome, is_disappeared_detection=True))
            self.seen_resolutions.add((venue, candidate.market_id))
        if written:
            accepted = await self.writer.write(written)
            self.total_resolved_since_start += accepted
            self.resolved_since_heartbeat += accepted
            self.disappeared_resolutions_since_heartbeat += accepted
        return DisappearedProcessingResult(
            candidates_seen=detection.disappeared_candidates_seen,
            skipped_as_still_active=detection.disappeared_skipped_as_still_active,
            markets_checked=len(detection.candidates),
            resolutions_detected=len(written),
        )

    async def _emit_heartbeat(self) -> None:
        self._logger.info(
            "resolution_watcher_heartbeat",
            markets_checked=self.markets_checked_since_heartbeat,
            metadata_candidates_seen=self.metadata_candidates_since_heartbeat,
            new_resolutions_detected=self.new_resolutions_since_heartbeat,
            api_fallbacks_used=self.api_fallbacks_since_heartbeat,
            disappeared_candidates_seen=self.disappeared_candidates_since_heartbeat,
            disappeared_skipped_as_still_active=(
                self.disappeared_skipped_as_still_active_since_heartbeat
            ),
            disappeared_resolutions_detected=self.disappeared_resolutions_since_heartbeat,
            markets_resolved_this_cycle=self.resolved_since_heartbeat,
            total_resolved_since_start=self.total_resolved_since_start,
        )
        self.markets_checked_since_heartbeat = 0
        self.resolved_since_heartbeat = 0
        self.metadata_candidates_since_heartbeat = 0
        self.new_resolutions_since_heartbeat = 0
        self.api_fallbacks_since_heartbeat = 0
        self.disappeared_candidates_since_heartbeat = 0
        self.disappeared_resolutions_since_heartbeat = 0
        self.disappeared_skipped_as_still_active_since_heartbeat = 0

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


@dataclass(frozen=True)
class ResolutionDetectionResult:
    metadata_candidates_seen: int
    candidates: list[MarketResolutionCandidate]


@dataclass(frozen=True)
class DisappearedDetectionResult:
    disappeared_candidates_seen: int
    disappeared_skipped_as_still_active: int
    candidates: list[MarketResolutionCandidate]


@dataclass(frozen=True)
class DisappearedProcessingResult:
    candidates_seen: int
    skipped_as_still_active: int
    markets_checked: int
    resolutions_detected: int


def detect_resolution_candidates(
    source_dir: Path,
    *,
    venue: str,
    seen: set[tuple[str, str]],
    now: datetime,
    lookback_days: int = 7,
) -> ResolutionDetectionResult:
    metadata_dir = source_dir / "market_metadata_snapshots"
    if not metadata_dir.exists() or not any(metadata_dir.rglob("*.parquet")):
        return ResolutionDetectionResult(metadata_candidates_seen=0, candidates=[])
    con = duckdb.connect()
    try:
        path = _sql_string(str(metadata_dir / "**" / "*.parquet"))
        columns = _metadata_columns(con, path)
        required_columns = {
            "is_resolved",
            "is_closed",
            "resolution_outcome",
            "resolution_timestamp_utc",
        }
        if not required_columns.issubset(columns):
            return ResolutionDetectionResult(metadata_candidates_seen=0, candidates=[])
        lower_bound = _to_utc(now).timestamp() - lookback_days * 86_400
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
                    venue_status_raw,
                    is_closed,
                    is_resolved,
                    resolution_outcome,
                    resolution_timestamp_utc::VARCHAR AS resolution_timestamp_text,
                    row_number() OVER (
                        PARTITION BY venue, market_id
                        ORDER BY captured_at_utc DESC
                    ) AS rn
                FROM read_parquet({path}, union_by_name = true)
                WHERE venue = ?
                  AND captured_at_utc >= to_timestamp(?)
            )
            SELECT
                venue,
                market_id,
                captured_at_text,
                end_date_text,
                status,
                raw_json,
                venue_status_raw,
                is_closed,
                is_resolved,
                resolution_outcome,
                resolution_timestamp_text
            FROM latest
            WHERE rn = 1
              AND (
                is_resolved = true
                OR is_closed = true
              )
            """,
            [venue, lower_bound],
        ).fetchall()
    finally:
        con.close()
    metadata_candidates_seen = len(rows)
    candidates = [
        MarketResolutionCandidate(
            venue=str(row[0]),
            market_id=str(row[1]),
            captured_at_utc=_parse_datetime(row[2]),
            end_date=None if row[3] is None else _parse_datetime(row[3]),
            status=None if row[4] is None else str(row[4]),
            raw_json=None if row[5] is None else str(row[5]),
            venue_status_raw=None if row[6] is None else str(row[6]),
            is_closed=None if row[7] is None else bool(row[7]),
            is_resolved=None if row[8] is None else bool(row[8]),
            resolution_outcome=None if row[9] is None else str(row[9]),
            resolution_timestamp_utc=None if row[10] is None else _parse_datetime(row[10]),
        )
        for row in rows
        if (str(row[0]), str(row[1])) not in seen
    ]
    return ResolutionDetectionResult(
        metadata_candidates_seen=metadata_candidates_seen,
        candidates=candidates,
    )


def detect_disappeared_candidates(
    source_dir: Path,
    *,
    venue: str,
    seen: set[tuple[str, str]],
    now: datetime,
    lookback_hours: int = 24,
    max_candidates: int = 20,
) -> DisappearedDetectionResult:
    """Return recently tracked markets missing from the current metadata cycle."""

    metadata_dir = source_dir / "market_metadata_snapshots"
    if not metadata_dir.exists() or not any(metadata_dir.rglob("*.parquet")):
        return DisappearedDetectionResult(
            disappeared_candidates_seen=0,
            disappeared_skipped_as_still_active=0,
            candidates=[],
        )
    con = duckdb.connect()
    try:
        path = _sql_string(str(metadata_dir / "**" / "*.parquet"))
        columns = _metadata_columns(con, path)
        lower_bound = _to_utc(now).timestamp() - lookback_hours * 3_600
        active_lower_bound = _to_utc(now).timestamp() - 30 * 60
        rows = con.execute(
            f"""
            WITH latest_recent AS (
                SELECT
                    {_metadata_candidate_select(columns)},
                    row_number() OVER (
                        PARTITION BY venue, market_id
                        ORDER BY captured_at_utc DESC
                    ) AS rn
                FROM read_parquet({path}, union_by_name = true)
                WHERE venue = ?
                  AND captured_at_utc >= to_timestamp(?)
            ),
            currently_active AS (
                SELECT DISTINCT venue, market_id
                FROM read_parquet({path}, union_by_name = true)
                WHERE venue = ?
                  AND captured_at_utc >= to_timestamp(?)
            )
            SELECT
                r.venue,
                r.market_id,
                r.captured_at_text,
                r.end_date_text,
                r.status,
                r.raw_json,
                r.venue_status_raw,
                r.is_closed,
                r.is_resolved,
                r.resolution_outcome,
                r.resolution_timestamp_text,
                r.accepting_orders
            FROM latest_recent r
            LEFT JOIN currently_active a
              ON r.venue = a.venue
             AND r.market_id = a.market_id
            WHERE r.rn = 1
              AND a.market_id IS NULL
            ORDER BY CAST(r.captured_at_text AS TIMESTAMPTZ) DESC
            """,
            [venue, lower_bound, venue, active_lower_bound],
        ).fetchall()
    finally:
        con.close()
    candidates = []
    skipped_as_still_active = 0
    for row in rows:
        if (str(row[0]), str(row[1])) in seen:
            continue
        if _is_skippable_polymarket_disappearance(row, now=now, columns=columns):
            skipped_as_still_active += 1
            continue
        candidates.append(_candidate_from_row(row))
    return DisappearedDetectionResult(
        disappeared_candidates_seen=len(candidates),
        disappeared_skipped_as_still_active=skipped_as_still_active,
        candidates=candidates[:max_candidates],
    )


def _outcome_from_metadata(
    candidate: MarketResolutionCandidate,
    *,
    detected_at: datetime,
    final_snapshot: FinalBookSnapshot,
) -> ResolvedMarketOutcome | None:
    resolved_value = _resolved_value(candidate.resolution_outcome)
    if resolved_value is None:
        return None
    return ResolvedMarketOutcome(
        venue=candidate.venue,
        market_id=candidate.market_id,
        resolution_timestamp_utc=detected_at,
        venue_resolved_at_utc=candidate.resolution_timestamp_utc,
        resolved_value=resolved_value,
        resolution_source="metadata_status",
        final_top_bid=final_snapshot.top_bid,
        final_top_ask=final_snapshot.top_ask,
        final_spread=final_snapshot.spread,
        final_snapshot_timestamp_utc=final_snapshot.timestamp_utc,
        metadata_snapshot_id=candidate.metadata_snapshot_id,
    )


def _resolved_value(outcome: str | None) -> float | None:
    if outcome is None:
        return None
    text = outcome.strip().lower()
    if text in {"yes", "y", "true", "1", "1.0"}:
        return 1.0
    if text in {"no", "n", "false", "0", "0.0"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def _metadata_columns(con: duckdb.DuckDBPyConnection, path: str) -> set[str]:
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet({path}, union_by_name = true)"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _metadata_candidate_select(columns: set[str]) -> str:
    return ",\n                    ".join(
        [
            "venue",
            "market_id",
            "captured_at_utc::VARCHAR AS captured_at_text",
            _nullable_select(columns, "end_date", "end_date_text", "TIMESTAMPTZ", stringify=True),
            _nullable_select(columns, "status", "status", "VARCHAR"),
            _nullable_select(columns, "raw_json", "raw_json", "VARCHAR"),
            _nullable_select(columns, "venue_status_raw", "venue_status_raw", "VARCHAR"),
            _nullable_select(columns, "is_closed", "is_closed", "BOOLEAN"),
            _nullable_select(columns, "is_resolved", "is_resolved", "BOOLEAN"),
            _nullable_select(columns, "resolution_outcome", "resolution_outcome", "VARCHAR"),
            _nullable_select(
                columns,
                "resolution_timestamp_utc",
                "resolution_timestamp_text",
                "TIMESTAMPTZ",
                stringify=True,
            ),
            _nullable_select(columns, "accepting_orders", "accepting_orders", "BOOLEAN"),
        ]
    )


def _nullable_select(
    columns: set[str],
    column: str,
    alias: str,
    sql_type: str,
    *,
    stringify: bool = False,
) -> str:
    if column not in columns:
        return f"CAST(NULL AS {sql_type}) AS {alias}"
    if stringify:
        return f"{column}::VARCHAR AS {alias}"
    return f"{column} AS {alias}"


def _candidate_from_row(row: tuple[object, ...]) -> MarketResolutionCandidate:
    return MarketResolutionCandidate(
        venue=str(row[0]),
        market_id=str(row[1]),
        captured_at_utc=_parse_datetime(row[2]),
        end_date=None if row[3] is None else _parse_datetime(row[3]),
        status=None if row[4] is None else str(row[4]),
        raw_json=None if row[5] is None else str(row[5]),
        venue_status_raw=None if row[6] is None else str(row[6]),
        is_closed=None if row[7] is None else bool(row[7]),
        is_resolved=None if row[8] is None else bool(row[8]),
        resolution_outcome=None if row[9] is None else str(row[9]),
        resolution_timestamp_utc=None if row[10] is None else _parse_datetime(row[10]),
    )


def _is_skippable_polymarket_disappearance(
    row: tuple[object, ...],
    *,
    now: datetime,
    columns: set[str],
) -> bool:
    """Return whether a Polymarket disappearance is likely just an active-market volume dip."""

    if str(row[0]) != "polymarket":
        return False
    required_columns = {"is_closed", "accepting_orders", "end_date"}
    if not required_columns.issubset(columns):
        return False
    is_closed = row[7]
    accepting_orders = row[11] if len(row) > 11 else None
    end_date = None if row[3] is None else _parse_datetime(row[3])
    if is_closed is True:
        return False
    if accepting_orders is False:
        return False
    if end_date is not None and end_date <= _to_utc(now) + timedelta(hours=24):
        return False
    return not (is_closed is None and accepting_orders is None and end_date is None)


def load_seen_resolutions(output_dir: Path) -> set[tuple[str, str]]:
    """Return persisted ``(venue, market_id)`` pairs from prior watcher runs."""

    if not output_dir.exists() or not any(output_dir.rglob("*.parquet")):
        return set()
    con = duckdb.connect()
    try:
        path = _sql_string(str(output_dir / "**" / "*.parquet"))
        columns = _metadata_columns(con, path)
        if not {"venue", "market_id"}.issubset(columns):
            return set()
        rows = con.execute(f"""
            SELECT DISTINCT venue, market_id
            FROM read_parquet({path}, union_by_name = true)
            WHERE venue IS NOT NULL
              AND market_id IS NOT NULL
            """).fetchall()
    finally:
        con.close()
    return {(str(row[0]), str(row[1])) for row in rows}


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
