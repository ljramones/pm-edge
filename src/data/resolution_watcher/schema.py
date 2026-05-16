"""Schema objects for resolved market outcomes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MarketResolutionCandidate:
    """One market metadata row that appears ready for resolution lookup."""

    venue: str
    market_id: str
    captured_at_utc: datetime
    end_date: datetime | None
    status: str | None
    raw_json: str | None = None
    venue_status_raw: str | None = None
    is_closed: bool | None = None
    is_resolved: bool | None = None
    resolution_outcome: str | None = None
    resolution_timestamp_utc: datetime | None = None

    @property
    def metadata_snapshot_id(self) -> str:
        return f"{self.venue}:{self.market_id}:{_to_utc(self.captured_at_utc).isoformat()}"

    def raw_payload(self) -> dict[str, Any]:
        if not self.raw_json:
            return {}
        try:
            payload = json.loads(self.raw_json)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class FinalBookSnapshot:
    """Final observed top-of-book state before resolution detection."""

    top_bid: float | None
    top_ask: float | None
    spread: float | None
    timestamp_utc: datetime | None


@dataclass(frozen=True)
class ResolvedMarketOutcome:
    """Resolved binary market outcome persisted by the watcher."""

    venue: str
    market_id: str
    resolution_timestamp_utc: datetime
    venue_resolved_at_utc: datetime | None
    resolved_value: float
    resolution_source: str
    final_top_bid: float | None
    final_top_ask: float | None
    final_spread: float | None
    final_snapshot_timestamp_utc: datetime | None
    metadata_snapshot_id: str | None
    schema_version: int = SCHEMA_VERSION

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "venue": self.venue,
            "market_id": self.market_id,
            "resolution_timestamp_utc": _to_utc(self.resolution_timestamp_utc),
            "venue_resolved_at_utc": (
                None if self.venue_resolved_at_utc is None else _to_utc(self.venue_resolved_at_utc)
            ),
            "resolved_value": self.resolved_value,
            "resolution_source": self.resolution_source,
            "final_top_bid": self.final_top_bid,
            "final_top_ask": self.final_top_ask,
            "final_spread": self.final_spread,
            "final_snapshot_timestamp_utc": (
                None
                if self.final_snapshot_timestamp_utc is None
                else _to_utc(self.final_snapshot_timestamp_utc)
            ),
            "metadata_snapshot_id": self.metadata_snapshot_id,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> ResolvedMarketOutcome:
        return cls(
            venue=str(record["venue"]),
            market_id=str(record["market_id"]),
            resolution_timestamp_utc=_datetime(record["resolution_timestamp_utc"]),
            venue_resolved_at_utc=(
                None
                if record.get("venue_resolved_at_utc") is None
                else _datetime(record["venue_resolved_at_utc"])
            ),
            resolved_value=float(record["resolved_value"]),
            resolution_source=str(record["resolution_source"]),
            final_top_bid=_float_or_none(record.get("final_top_bid")),
            final_top_ask=_float_or_none(record.get("final_top_ask")),
            final_spread=_float_or_none(record.get("final_spread")),
            final_snapshot_timestamp_utc=(
                None
                if record.get("final_snapshot_timestamp_utc") is None
                else _datetime(record["final_snapshot_timestamp_utc"])
            ),
            metadata_snapshot_id=(
                None
                if record.get("metadata_snapshot_id") is None
                else str(record["metadata_snapshot_id"])
            ),
            schema_version=int(record.get("schema_version", SCHEMA_VERSION)),
        )


def resolved_market_outcome_schema() -> pa.Schema:
    """Return the parquet schema for resolved market outcomes."""

    return pa.schema(
        [
            ("schema_version", pa.int16()),
            ("venue", pa.string()),
            ("market_id", pa.string()),
            ("resolution_timestamp_utc", pa.timestamp("us", tz="UTC")),
            ("venue_resolved_at_utc", pa.timestamp("us", tz="UTC")),
            ("resolved_value", pa.float64()),
            ("resolution_source", pa.string()),
            ("final_top_bid", pa.float64()),
            ("final_top_ask", pa.float64()),
            ("final_spread", pa.float64()),
            ("final_snapshot_timestamp_utc", pa.timestamp("us", tz="UTC")),
            ("metadata_snapshot_id", pa.string()),
        ]
    )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _to_utc(value)
    parsed = datetime.fromisoformat(str(value))
    return _to_utc(parsed)


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
