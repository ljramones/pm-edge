"""Activity filters for deciding which markets receive book subscriptions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

REJECTION_REASON_KEYS = (
    "rejected_low_volume",
    "rejected_wide_spread",
    "rejected_stale_trade",
    "rejected_too_new",
    "rejected_too_close_to_end",
)


@dataclass(frozen=True)
class ActivityThresholds:
    """Thresholds for forward-indexer market activity."""

    min_24h_volume_usd: float = 10_000.0
    max_spread_cents: float = 10.0
    max_last_trade_age_hours: float = 24.0
    min_market_age_minutes: float = 30.0
    min_time_to_close_hours: float = 2.0


def market_passes_activity_filter(
    *,
    volume_24h: float | None,
    spread: float | None,
    last_trade_at: datetime | None,
    created_at: datetime | None,
    end_date: datetime | None,
    thresholds: ActivityThresholds,
    now: datetime | None = None,
) -> bool:
    """Return whether a market should receive live book/trade subscriptions."""

    return (
        activity_filter_rejection_reason(
            volume_24h=volume_24h,
            spread=spread,
            last_trade_at=last_trade_at,
            created_at=created_at,
            end_date=end_date,
            thresholds=thresholds,
            now=now,
        )
        is None
    )


def activity_filter_rejection_reason(
    *,
    volume_24h: float | None,
    spread: float | None,
    last_trade_at: datetime | None,
    created_at: datetime | None,
    end_date: datetime | None,
    thresholds: ActivityThresholds,
    now: datetime | None = None,
) -> str | None:
    """Return the first activity-filter rejection reason, or None when accepted."""

    timestamp = _aware(now or datetime.now(tz=UTC))
    if volume_24h is None or volume_24h < thresholds.min_24h_volume_usd:
        return "rejected_low_volume"
    if spread is None or spread * 100 > thresholds.max_spread_cents:
        return "rejected_wide_spread"
    if last_trade_at is None:
        return "rejected_stale_trade"
    if _aware(last_trade_at) < timestamp - timedelta(hours=thresholds.max_last_trade_age_hours):
        return "rejected_stale_trade"
    if created_at is not None and _aware(created_at) > timestamp - timedelta(
        minutes=thresholds.min_market_age_minutes
    ):
        return "rejected_too_new"
    if end_date is not None and _aware(end_date) < timestamp + timedelta(
        hours=thresholds.min_time_to_close_hours
    ):
        return "rejected_too_close_to_end"
    return None


def empty_rejection_counts() -> dict[str, int]:
    """Return a zero-filled rejection reason counter."""

    return dict.fromkeys(REJECTION_REASON_KEYS, 0)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
