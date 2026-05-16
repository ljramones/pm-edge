"""Core types for the historical execution simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, cast

OrderSide = Literal["buy", "sell"]
OrderStatus = Literal["filled", "partial", "unfilled", "error"]


@dataclass(frozen=True)
class OrderSpec:
    """A single hypothetical order to simulate against historical book state."""

    market_id: str
    venue: str
    side: OrderSide
    size: float
    limit_price: float | None
    submitted_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
            "venue": self.venue,
            "side": self.side,
            "size": self.size,
            "limit_price": self.limit_price,
            "submitted_at": self.submitted_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrderSpec:
        return cls(
            market_id=str(data["market_id"]),
            venue=str(data["venue"]),
            side=_order_side(data["side"]),
            size=float(data["size"]),
            limit_price=None if data.get("limit_price") is None else float(data["limit_price"]),
            submitted_at=datetime.fromisoformat(str(data["submitted_at"])),
        )


@dataclass(frozen=True)
class FillOutcome:
    """Result of simulating one order."""

    status: OrderStatus
    requested_size: float
    filled_size: float = 0.0
    filled_price: float | None = None
    slippage: float | None = None
    time_to_fill: timedelta | None = None
    fees: float = 0.0
    assumptions_triggered: list[str] = field(default_factory=list)
    market_id: str = ""
    venue: str = ""
    side: OrderSide | None = None
    submitted_at: datetime | None = None
    fill_timestamp: datetime | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "requested_size": self.requested_size,
            "filled_size": self.filled_size,
            "filled_price": self.filled_price,
            "slippage": self.slippage,
            "time_to_fill_seconds": (
                self.time_to_fill.total_seconds() if self.time_to_fill is not None else None
            ),
            "fees": self.fees,
            "assumptions_triggered": list(self.assumptions_triggered),
            "market_id": self.market_id,
            "venue": self.venue,
            "side": self.side,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "fill_timestamp": self.fill_timestamp.isoformat() if self.fill_timestamp else None,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FillOutcome:
        seconds = data.get("time_to_fill_seconds")
        return cls(
            status=_order_status(data["status"]),
            requested_size=float(data["requested_size"]),
            filled_size=float(data.get("filled_size") or 0.0),
            filled_price=None if data.get("filled_price") is None else float(data["filled_price"]),
            slippage=None if data.get("slippage") is None else float(data["slippage"]),
            time_to_fill=None if seconds is None else timedelta(seconds=float(seconds)),
            fees=float(data.get("fees") or 0.0),
            assumptions_triggered=list(data.get("assumptions_triggered") or []),
            market_id=str(data.get("market_id") or ""),
            venue=str(data.get("venue") or ""),
            side=None if data.get("side") is None else _order_side(data["side"]),
            submitted_at=(
                None
                if data.get("submitted_at") is None
                else datetime.fromisoformat(str(data["submitted_at"]))
            ),
            fill_timestamp=(
                None
                if data.get("fill_timestamp") is None
                else datetime.fromisoformat(str(data["fill_timestamp"]))
            ),
            error=None if data.get("error") is None else str(data["error"]),
        )


@dataclass(frozen=True)
class BookSnapshot:
    """Point-in-time book state consumed by fill simulation."""

    venue: str
    market_id: str
    timestamp_utc: datetime
    bid_levels: list[dict[str, float]]
    ask_levels: list[dict[str, float]]
    top_bid: float | None
    top_ask: float | None
    mid: float | None
    spread: float | None
    snapshot_source: str

    def age_at(self, submitted_at: datetime) -> float:
        return (submitted_at - self.timestamp_utc).total_seconds()


@dataclass(frozen=True)
class AssumptionResult:
    """One empirical validation result for a simulator assumption."""

    name: str
    empirical_value: float | None
    threshold: float
    passed: bool
    note: str


@dataclass(frozen=True)
class AssumptionReport:
    """Collection of assumption validation results."""

    results: list[AssumptionResult]

    def to_text(self) -> str:
        lines = ["Execution simulator assumption report:"]
        for result in self.results:
            value = "n/a" if result.empirical_value is None else f"{result.empirical_value:.4f}"
            status = "PASS" if result.passed else "FAIL"
            lines.append(f"- {status} {result.name}: value={value}, threshold={result.threshold}")
            lines.append(f"  {result.note}")
        return "\n".join(lines)


def _order_side(value: Any) -> OrderSide:
    if value not in {"buy", "sell"}:
        raise ValueError(f"Unsupported order side: {value}")
    return cast(OrderSide, value)


def _order_status(value: Any) -> OrderStatus:
    if value not in {"filled", "partial", "unfilled", "error"}:
        raise ValueError(f"Unsupported order status: {value}")
    return cast(OrderStatus, value)
