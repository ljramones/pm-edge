"""Polling data normalization and aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from math import exp, sqrt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from core.models import PollAggregateRecord, PollObservation, utc_now
from data.database import HistoricalMarketStore
from utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_POLLSTER_QUALITY: dict[str, float] = {
    "a+": 1.20,
    "a": 1.15,
    "a-": 1.10,
    "b+": 1.05,
    "b": 1.00,
    "b-": 0.95,
    "c+": 0.90,
    "c": 0.85,
    "c-": 0.80,
}


class PollRecord(BaseModel):
    """Clean poll result for one candidate/outcome."""

    model_config = ConfigDict(frozen=True)

    event_slug: str
    candidate: str
    support: float = Field(ge=0, le=1)
    pollster: str
    end_date: datetime
    market_id: str | None = None
    pollster_grade: str | None = None
    population: str | None = None
    sample_size: int | None = Field(default=None, gt=0)
    start_date: datetime | None = None
    source_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PollAggregate(BaseModel):
    """Weighted aggregate for one candidate/outcome."""

    model_config = ConfigDict(frozen=True)

    event_slug: str
    candidate: str
    probability: float = Field(ge=0, le=1)
    as_of: datetime
    market_id: str | None = None
    poll_count: int
    effective_sample_size: float = 0.0


class PollAggregator:
    """Normalize, weight, aggregate, and persist polling data."""

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        pollster_quality: dict[str, float] | None = None,
        half_life_days: float = 21.0,
    ) -> None:
        self.store = HistoricalMarketStore(engine=engine)
        self.pollster_quality = pollster_quality or DEFAULT_POLLSTER_QUALITY
        self.half_life_days = half_life_days

    def normalize_records(self, rows: Iterable[dict[str, Any]]) -> list[PollRecord]:
        """Normalize source-specific poll rows into candidate-level records."""

        records: list[PollRecord] = []
        for row in rows:
            event_slug = str(row.get("event_slug") or row.get("race") or row.get("event") or "")
            pollster = str(row.get("pollster") or row.get("pollster_name") or "unknown")
            end_date = _parse_datetime(
                row.get("end_date") or row.get("date") or row.get("field_date")
            )
            start_date = _parse_optional_datetime(row.get("start_date"))
            sample_size = _optional_int(
                row.get("sample_size") or row.get("samplesize") or row.get("n")
            )
            grade = row.get("pollster_grade") or row.get("grade")

            candidate_rows = _candidate_support_rows(row)
            for candidate, support in candidate_rows:
                if not event_slug or not candidate:
                    continue
                records.append(
                    PollRecord(
                        event_slug=event_slug,
                        market_id=_optional_str(row.get("market_id")),
                        candidate=candidate,
                        support=_normalize_support(support),
                        pollster=pollster,
                        pollster_grade=_optional_str(grade),
                        population=_optional_str(row.get("population")),
                        sample_size=sample_size,
                        start_date=start_date,
                        end_date=end_date,
                        source_url=_optional_str(row.get("source_url") or row.get("url")),
                        raw=row,
                    )
                )
        return records

    def aggregate(
        self,
        records: Sequence[PollRecord],
        *,
        as_of: datetime | None = None,
    ) -> list[PollAggregate]:
        """Return weighted candidate aggregates for the provided records."""

        if not records:
            return []

        aggregate_time = as_of or max(record.end_date for record in records)
        grouped: dict[tuple[str, str, str | None], list[PollRecord]] = defaultdict(list)
        for record in records:
            grouped[(record.event_slug, record.candidate, record.market_id)].append(record)

        aggregates: list[PollAggregate] = []
        for (event_slug, candidate, market_id), candidate_records in grouped.items():
            weighted_support = Decimal("0")
            total_weight = Decimal("0")
            effective_sample_size = Decimal("0")
            for record in candidate_records:
                weight = self.record_weight(record, as_of=aggregate_time)
                weighted_support += Decimal(str(record.support)) * weight
                total_weight += weight
                if record.sample_size:
                    effective_sample_size += Decimal(str(record.sample_size)) * weight

            probability = float(weighted_support / total_weight) if total_weight else 0.5
            aggregates.append(
                PollAggregate(
                    event_slug=event_slug,
                    market_id=market_id,
                    candidate=candidate,
                    probability=max(0.0, min(1.0, probability)),
                    as_of=aggregate_time,
                    poll_count=len(candidate_records),
                    effective_sample_size=float(effective_sample_size),
                )
            )

        return aggregates

    def record_weight(self, record: PollRecord, *, as_of: datetime | None = None) -> Decimal:
        """Compute poll weight from quality, sample size, and recency."""

        anchor = as_of or utc_now()
        age_days = max((anchor - record.end_date).total_seconds() / 86_400, 0.0)
        quality = self.pollster_quality.get((record.pollster_grade or "b").lower(), 1.0)
        sample_weight = sqrt(record.sample_size or 600) / sqrt(600)
        recency = exp(-0.69314718056 * age_days / self.half_life_days)
        return Decimal(str(quality * sample_weight * recency))

    def save_records(self, records: Sequence[PollRecord]) -> list[PollObservation]:
        """Persist normalized poll observations."""

        self.store.init_db()
        observations = [
            PollObservation(
                event_slug=record.event_slug,
                market_id=record.market_id,
                pollster=record.pollster,
                pollster_grade=record.pollster_grade,
                population=record.population,
                sample_size=record.sample_size,
                start_date=record.start_date,
                end_date=record.end_date,
                candidate=record.candidate,
                support=Decimal(str(record.support)),
                weight=self.record_weight(record),
                source_url=record.source_url,
                raw=record.raw,
            )
            for record in records
        ]
        with Session(self.store.engine) as session:
            session.add_all(observations)
            session.commit()
            for observation in observations:
                session.refresh(observation)
        return observations

    def save_aggregates(self, aggregates: Sequence[PollAggregate]) -> list[PollAggregateRecord]:
        """Persist weighted poll aggregates."""

        self.store.init_db()
        rows = [
            PollAggregateRecord(
                event_slug=aggregate.event_slug,
                market_id=aggregate.market_id,
                as_of=aggregate.as_of,
                candidate=aggregate.candidate,
                probability=Decimal(str(aggregate.probability)),
                poll_count=aggregate.poll_count,
                effective_sample_size=Decimal(str(aggregate.effective_sample_size)),
                raw=aggregate.model_dump(mode="json"),
            )
            for aggregate in aggregates
        ]
        with Session(self.store.engine) as session:
            session.add_all(rows)
            session.commit()
            for row in rows:
                session.refresh(row)
        return rows

    def get_latest_aggregate(
        self,
        *,
        event_slug: str | None = None,
        market_id: str | None = None,
    ) -> list[PollAggregate]:
        """Return latest persisted aggregate rows for an event or market."""

        if not event_slug and not market_id:
            raise ValueError("event_slug or market_id is required.")

        with Session(self.store.engine) as session:
            statement = select(PollAggregateRecord)
            if market_id:
                statement = statement.where(PollAggregateRecord.market_id == market_id)
            if event_slug:
                statement = statement.where(PollAggregateRecord.event_slug == event_slug)
            rows = list(
                session.exec(statement.order_by(desc(PollAggregateRecord.as_of)))  # type: ignore[arg-type]
            )

        if not rows:
            return []

        latest_as_of = rows[0].as_of
        return [
            PollAggregate(
                event_slug=row.event_slug,
                market_id=row.market_id,
                candidate=row.candidate,
                probability=float(row.probability),
                as_of=row.as_of,
                poll_count=row.poll_count,
                effective_sample_size=float(row.effective_sample_size),
            )
            for row in rows
            if row.as_of == latest_as_of
        ]

    def historical_series(
        self,
        *,
        event_slug: str | None = None,
        market_id: str | None = None,
    ) -> list[PollAggregate]:
        """Return all persisted aggregate rows for an event or market."""

        if not event_slug and not market_id:
            raise ValueError("event_slug or market_id is required.")

        with Session(self.store.engine) as session:
            statement = select(PollAggregateRecord)
            if market_id:
                statement = statement.where(PollAggregateRecord.market_id == market_id)
            if event_slug:
                statement = statement.where(PollAggregateRecord.event_slug == event_slug)
            rows = list(session.exec(statement.order_by(PollAggregateRecord.as_of)))  # type: ignore[arg-type]

        return [
            PollAggregate(
                event_slug=row.event_slug,
                market_id=row.market_id,
                candidate=row.candidate,
                probability=float(row.probability),
                as_of=row.as_of,
                poll_count=row.poll_count,
                effective_sample_size=float(row.effective_sample_size),
            )
            for row in rows
        ]


def _candidate_support_rows(row: dict[str, Any]) -> list[tuple[str, Any]]:
    if "candidate" in row and "support" in row:
        return [(str(row["candidate"]), row["support"])]
    if "answers" in row and isinstance(row["answers"], list):
        return [
            (str(answer.get("candidate") or answer.get("choice")), answer.get("support"))
            for answer in row["answers"]
        ]
    return [
        (key.removeprefix("pct_"), value) for key, value in row.items() if key.startswith("pct_")
    ]


def _normalize_support(value: Any) -> float:
    support = float(value)
    if support > 1:
        support /= 100
    return max(0.0, min(1.0, support))


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return _parse_datetime(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
