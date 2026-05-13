from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlmodel import create_engine

from backtesting import (
    BacktestConfig,
    Backtester,
    EvaluationRubric,
    WalkForwardConfig,
    WalkForwardSplitter,
)
from scripts.backtest import demo_signals


def test_walk_forward_split_respects_resolution_dates() -> None:
    frame = demo_signals()
    splitter = WalkForwardSplitter(
        WalkForwardConfig(
            train_window_days=120, test_window_days=30, step_days=30, min_train_observations=5
        )
    )

    splits = splitter.split(frame)

    assert splits
    first = splits[0]
    train_rows = frame[
        (pd.to_datetime(frame["as_of"], utc=True) < first.train_end)
        & (pd.to_datetime(frame["resolved_at"], utc=True) <= first.train_end)
    ]
    assert len(train_rows) >= 5


def test_backtester_simulates_and_scores_bets() -> None:
    engine = create_engine("sqlite:///:memory:")
    config = BacktestConfig(save_results=True, edge_threshold=0.02, stake=50)
    result = Backtester(config=config, engine=engine).run(demo_signals())

    assert result.bets
    assert result.report.metrics["bet_count"] > 0
    assert result.rubric.grade in {"Decision-Grade", "Promising", "Fail"}


def test_rubric_decision_grade_thresholds() -> None:
    decision = EvaluationRubric().evaluate(
        {
            "mean_edge": 0.05,
            "brier_score": 0.15,
            "sharpe": 1.5,
            "net_pnl": 100,
            "profit_factor": 1.5,
            "bet_count": 60,
        }
    )

    assert decision.grade == "Decision-Grade"


def test_backtester_period_filter() -> None:
    result = Backtester(BacktestConfig(save_results=False)).run(
        demo_signals(),
        period_start=datetime(2025, 1, 1, tzinfo=UTC),
        period_end=datetime(2025, 6, 1, tzinfo=UTC),
    )

    assert all(
        pd.Timestamp(row["as_of"]) <= pd.Timestamp("2025-06-01", tz=UTC) for row in result.bets
    )


def test_backtester_requires_resolved_outcomes_with_clear_message() -> None:
    frame = pd.DataFrame(
        {
            "market_id": ["m1"],
            "as_of": [pd.Timestamp("2025-01-01", tz="UTC")],
            "venue": ["polymarket"],
            "market_probability": [0.45],
            "model_probability": [0.55],
        }
    )

    with pytest.raises(ValueError, match="--include-outcomes"):
        Backtester(BacktestConfig(save_results=False)).run(frame)


def test_backtester_excludes_lookahead_rows_by_default() -> None:
    frame = pd.DataFrame(
        {
            "market_id": ["m1", "m2"],
            "as_of": pd.date_range("2025-01-01", periods=2, tz="UTC"),
            "resolved_at": pd.date_range("2025-01-08", periods=2, tz="UTC"),
            "venue": ["polymarket", "polymarket"],
            "market_probability": [0.45, 0.45],
            "model_probability": [0.55, 0.55],
            "outcome": [1, 1],
            "is_lookahead": [True, False],
        }
    )

    result = Backtester(BacktestConfig(save_results=False, edge_threshold=0.02)).run(frame)

    assert len(result.bets) == 1
    assert result.bets[0]["market_id"] == "m2"
