"""Deterministic signal backtester for Phase 2 evaluation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from backtesting.data_split import WalkForwardConfig, WalkForwardSplit, WalkForwardSplitter
from backtesting.metrics import BacktestMetrics, EvaluationReport
from backtesting.rubric import EvaluationRubric, RubricDecision
from core.config import Settings, get_settings
from core.models import BacktestBet, BacktestRun, Venue
from utils.logging import get_logger

logger = get_logger(__name__)


class FeeModel(BaseModel):
    """Configurable venue fee and slippage assumptions."""

    model_config = ConfigDict(frozen=True)

    polymarket_fee_bps: float = 0.0
    kalshi_fee_bps: float = 7.0
    slippage_bps: float = 15.0

    def fee_rate(self, venue: Venue | str) -> float:
        """Return fee rate for a venue."""

        normalized = Venue(str(venue))
        if normalized == Venue.KALSHI:
            return self.kalshi_fee_bps / 10_000
        return self.polymarket_fee_bps / 10_000

    @property
    def slippage_rate(self) -> float:
        """Return slippage as a decimal rate."""

        return self.slippage_bps / 10_000


class BacktestConfig(BaseModel):
    """Backtest strategy and execution settings."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str = "gbdt_v1"
    edge_threshold: float = 0.02
    stake: float = 100.0
    starting_capital: float = 10_000.0
    fee_model: FeeModel = Field(default_factory=FeeModel)
    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)
    save_results: bool = True


class BacktestResult(BaseModel):
    """Backtest output object."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    bets: list[dict[str, object]] = Field(default_factory=list)
    report: EvaluationReport
    rubric: RubricDecision
    splits: list[WalkForwardSplit] = Field(default_factory=list)

    def bets_frame(self) -> pd.DataFrame:
        """Return simulated bets as a DataFrame."""

        return pd.DataFrame(self.bets)


class Backtester:
    """Run deterministic walk-forward signal backtests from feature/signal rows."""

    def __init__(
        self,
        config: BacktestConfig | None = None,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.config = config or BacktestConfig()
        self.settings = settings or get_settings()
        self.engine = engine or create_engine(self.settings.database_url)
        self.metrics = BacktestMetrics()
        self.rubric = EvaluationRubric()

    def run(
        self,
        signals: pd.DataFrame,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> BacktestResult:
        """Run a walk-forward backtest from historical signal rows.

        Required columns: market_id, as_of, resolved_at, venue, market_probability,
        model_probability, outcome.
        """

        run_id = str(uuid4())
        frame = normalize_signal_frame(signals)
        if period_start is not None:
            frame = frame[frame["as_of"] >= pd.Timestamp(period_start)]
        if period_end is not None:
            frame = frame[frame["as_of"] <= pd.Timestamp(period_end)]

        splits = WalkForwardSplitter(self.config.walk_forward).split(frame)
        if not splits:
            # For small deterministic fixtures, evaluate all rows as one holdout
            # while still preserving the same simulation rules.
            bets = self._simulate_period(frame, run_id=run_id)
        else:
            bets = pd.concat(
                [
                    self._simulate_period(
                        frame[
                            (frame["as_of"] >= split.test_start) & (frame["as_of"] < split.test_end)
                        ],
                        run_id=run_id,
                    )
                    for split in splits
                ],
                ignore_index=True,
            )

        report = self.metrics.evaluate(bets)
        decision = self.rubric.evaluate(report.metrics)
        result = BacktestResult(
            run_id=run_id,
            bets=bets.to_dict(orient="records"),
            report=report,
            rubric=decision,
            splits=splits,
        )
        if self.config.save_results:
            self.save_result(result, period_start=period_start, period_end=period_end)
        logger.info(
            "backtest_completed",
            run_id=run_id,
            strategy=self.config.strategy_name,
            bets=len(result.bets),
            grade=decision.grade,
        )
        return result

    def save_result(
        self,
        result: BacktestResult,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> None:
        """Persist backtest run and simulated bets."""

        SQLModel.metadata.create_all(self.engine)
        run = BacktestRun(
            id=result.run_id,
            strategy_name=self.config.strategy_name,
            period_start=period_start,
            period_end=period_end,
            config=self.config.model_dump(mode="json"),
            metrics={key: _json_float(value) for key, value in result.report.metrics.items()},
            rubric_grade=result.rubric.grade,
        )
        bet_rows = [
            BacktestBet(
                run_id=result.run_id,
                market_id=str(row["market_id"]),
                category=_optional_str(row.get("category")),
                signal_time=pd.Timestamp(row["as_of"]).to_pydatetime(),
                resolution_time=pd.Timestamp(row["resolved_at"]).to_pydatetime(),
                market_probability=Decimal(str(row["market_probability"])),
                model_probability=Decimal(str(row["model_probability"])),
                edge=Decimal(str(row["edge"])),
                threshold=Decimal(str(self.config.edge_threshold)),
                stake=Decimal(str(row["stake"])),
                entry_price=Decimal(str(row["entry_price"])),
                slippage=Decimal(str(row["slippage"])),
                fee=Decimal(str(row["fee"])),
                outcome=int(cast(float | int | str, row["outcome"])),
                pnl=Decimal(str(row["pnl"])),
                return_on_capital=Decimal(str(row["return_on_capital"])),
                raw={key: _json_value(value) for key, value in row.items()},
            )
            for row in result.bets
        ]
        with Session(self.engine) as session:
            session.add(run)
            session.add_all(bet_rows)
            session.commit()

    def _simulate_period(self, frame: pd.DataFrame, *, run_id: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()
        rows: list[dict[str, object]] = []
        for row in frame.to_dict(orient="records"):
            model_probability = float(cast(float | int | str, row["model_probability"]))
            market_probability = float(cast(float | int | str, row["market_probability"]))
            edge = model_probability - market_probability
            if abs(edge) < self.config.edge_threshold:
                continue
            rows.append(self._simulate_bet(row, edge=edge, run_id=run_id))
        return pd.DataFrame(rows)

    def _simulate_bet(
        self, row: dict[str, object], *, edge: float, run_id: str
    ) -> dict[str, object]:
        venue = Venue(str(row.get("venue", Venue.POLYMARKET.value)))
        market_probability = float(cast(float | int | str, row["market_probability"]))
        model_probability = float(cast(float | int | str, row["model_probability"]))
        outcome = int(cast(float | int | str, row["outcome"]))
        stake = self.config.stake
        direction = 1 if edge > 0 else -1
        raw_entry = market_probability if direction > 0 else 1 - market_probability
        slippage = raw_entry * self.config.fee_model.slippage_rate
        entry_price = min(max(raw_entry + slippage, 0.001), 0.999)
        fee = stake * self.config.fee_model.fee_rate(venue)
        wins = outcome == 1 if direction > 0 else outcome == 0
        gross_pnl = stake * ((1 - entry_price) / entry_price) if wins else -stake
        pnl = gross_pnl - fee
        return {
            "run_id": run_id,
            "market_id": row["market_id"],
            "category": row.get("category"),
            "as_of": row["as_of"],
            "resolved_at": row["resolved_at"],
            "venue": venue.value,
            "market_probability": market_probability,
            "model_probability": model_probability,
            "edge": edge,
            "stake": stake,
            "entry_price": entry_price,
            "slippage": slippage,
            "fee": fee,
            "outcome": outcome,
            "pnl": pnl,
            "return_on_capital": pnl / stake,
        }


def normalize_signal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize and validate signal rows for backtesting."""

    required = {
        "market_id",
        "as_of",
        "resolved_at",
        "venue",
        "market_probability",
        "model_probability",
        "outcome",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required signal columns: {sorted(missing)}")
    output = frame.copy()
    output["as_of"] = pd.to_datetime(output["as_of"], utc=True)
    output["resolved_at"] = pd.to_datetime(output["resolved_at"], utc=True)
    output["market_probability"] = output["market_probability"].astype(float).clip(0.001, 0.999)
    output["model_probability"] = output["model_probability"].astype(float).clip(0.001, 0.999)
    output["outcome"] = output["outcome"].astype(int)
    return output.sort_values("as_of").reset_index(drop=True)


def _json_float(value: float) -> float | str:
    if value == float("inf"):
        return "inf"
    if value == float("-inf"):
        return "-inf"
    return float(value)


def _json_value(value: object) -> object:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
