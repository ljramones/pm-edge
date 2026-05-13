from pathlib import Path

import pandas as pd

from scripts.generate_signals import (
    SIGNAL_COLUMNS,
    active_resolved_market_rows,
    apply_walk_forward_model,
    attach_resolved_outcomes,
    coerce_single_file_output,
    ensure_signal_schema,
    is_single_file_output,
    iter_timestamps,
    partition_path,
    prepare_single_file_output,
    resolved_signal_row,
    write_demo_signals,
    write_resolved_market_signals,
)


def test_generate_signals_cli_coerces_directory_style_output_to_file() -> None:
    assert coerce_single_file_output(Path("data/processed/signals")) == Path(
        "data/processed/signals.parquet"
    )
    assert coerce_single_file_output(Path("data/processed/signals.parquet")) == Path(
        "data/processed/signals.parquet"
    )


def test_generate_signals_demo_writes_partitioned_parquet(tmp_path: Path) -> None:
    timestamps = iter_timestamps("2025-03-01", "2025-03-01", 6)

    write_demo_signals(timestamps, output=tmp_path, overwrite=False)
    path = partition_path(tmp_path, timestamps[0])

    assert path.exists()
    frame = pd.read_parquet(path)
    assert set(SIGNAL_COLUMNS).issubset(frame.columns)
    assert {"question", "outcome", "resolved_at", "as_of"}.issubset(frame.columns)


def test_generate_signals_demo_can_write_single_file(tmp_path: Path) -> None:
    timestamps = iter_timestamps("2025-03-01", "2025-03-02", 24)
    output = tmp_path / "signals.parquet"

    write_demo_signals(timestamps, output=output, overwrite=True)

    assert is_single_file_output(output)
    assert output.is_file()
    frame = pd.read_parquet(output)
    assert len(frame) == 6
    assert set(SIGNAL_COLUMNS).issubset(frame.columns)
    assert frame["fear_sizing_multiplier"].eq(1.0).all()


def test_single_file_output_overwrite_replaces_existing_directory(tmp_path: Path) -> None:
    output = tmp_path / "signals.parquet"
    output.mkdir()
    (output / "date=2024-01-01").mkdir()

    prepare_single_file_output(output, overwrite=True)

    assert not output.exists()
    write_demo_signals(
        iter_timestamps("2025-03-01", "2025-03-01", 24),
        output=output,
        overwrite=True,
    )
    assert output.is_file()


def test_generate_signals_demo_can_include_advanced_features(tmp_path: Path) -> None:
    timestamps = iter_timestamps("2025-03-01", "2025-03-01", 6)

    write_demo_signals(timestamps, output=tmp_path, overwrite=False, include_advanced=True)
    frame = pd.read_parquet(partition_path(tmp_path, timestamps[0]))

    assert frame["advanced_enabled"].all()
    assert "llm_probability" in frame.iloc[0]["features"]


def test_attach_resolved_outcomes_fills_backtest_columns() -> None:
    signals = ensure_signal_schema(
        pd.DataFrame(
            {
                "market_id": ["m1"],
                "question": ["Will BTC close above 100k?"],
                "as_of": [pd.Timestamp("2025-01-01", tz="UTC")],
                "venue": ["polymarket"],
                "market_probability": [0.45],
                "model_probability": [0.55],
                "edge": [0.10],
                "confidence": [0.8],
            }
        )
    )
    resolved = pd.DataFrame(
        {
            "market_id": ["m1"],
            "winning_outcome": ["Yes"],
            "closed_time": ["2025-01-08T00:00:00Z"],
        }
    )

    output = attach_resolved_outcomes(signals, resolved)

    assert output.loc[0, "outcome"] == 1
    assert pd.Timestamp(output.loc[0, "resolved_at"]) == pd.Timestamp("2025-01-08T00:00:00Z")


def test_resolved_market_signal_generation_uses_backfill_universe(tmp_path: Path) -> None:
    timestamps = iter_timestamps("2024-01-01", "2024-01-02", 24)
    resolved = pd.DataFrame(
        {
            "market_id": ["m1"],
            "question": ["Will BTC be above 100k?"],
            "slug": ["will-btc-be-above-100k"],
            "condition_id": ["c1"],
            "tags": [["crypto", "bitcoin"]],
            "start_date": ["2023-12-01T00:00:00Z"],
            "closed_time": ["2024-01-10T00:00:00Z"],
            "winning_outcome": ["No"],
            "last_trade_price": [0.12],
            "yes_price": [0.0],
            "no_price": [1.0],
            "volume_num": [750_000],
            "liquidity_num": [25_000],
            "best_bid": [0.10],
            "best_ask": [0.14],
        }
    )
    output = tmp_path / "signals.parquet"

    write_resolved_market_signals(
        timestamps,
        resolved_markets=resolved,
        output=output,
        overwrite=True,
        single_file=True,
        crypto_only=True,
        high_volume_only=True,
        min_volume=500_000,
        include_advanced=True,
    )

    frame = pd.read_parquet(output)
    assert len(frame) == 2
    assert frame["outcome"].eq(0).all()
    assert frame["advanced_enabled"].all()
    assert "advanced_model_probability" in frame.columns


def test_apply_walk_forward_model_sets_trained_probability(tmp_path: Path) -> None:
    rows = 260
    dates = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "market_id": [f"m-{index}" for index in range(rows)],
            "question": [f"Will BTC signal {index} resolve yes?" for index in range(rows)],
            "as_of": dates,
            "resolved_at": dates + pd.Timedelta(days=1),
            "venue": ["polymarket"] * rows,
            "market_probability": [0.35 + (index % 7) * 0.04 for index in range(rows)],
            "model_probability": [0.5] * rows,
            "edge": [0.0] * rows,
            "confidence": [0.1] * rows,
            "outcome": [index % 2 for index in range(rows)],
            "liquidity": [10_000 + index for index in range(rows)],
            "volume": [100_000 + index * 10 for index in range(rows)],
            "fear_sizing_multiplier": [1.0] * rows,
            "features": [
                {
                    "llm_probability": 0.45 + 0.1 * (index % 2),
                    "llm_news_score": -0.1 + 0.2 * (index % 2),
                    "onchain_volume_surge": float(index % 5),
                }
                for index in range(rows)
            ],
        }
    )

    output = apply_walk_forward_model(
        frame,
        model_output=tmp_path / "gbdt.pkl",
        min_train_rows=60,
    )

    predicted = output["trained_model_probability"].notna()
    assert predicted.any()
    assert (tmp_path / "gbdt.pkl").exists()
    assert output.loc[predicted, "reasoning"].map(str).str.contains("gbdt walk-forward").all()


def test_resolved_signal_row_uses_historical_price_when_available() -> None:
    row = {
        "market_id": "m1",
        "question": "Will BTC close above 100k?",
        "closed_time": "2024-01-10T00:00:00Z",
        "winning_outcome": "Yes",
        "last_trade_price": 0.99,
        "volume_num": 750_000,
        "liquidity_num": 25_000,
    }
    history = pd.DataFrame(
        {
            "market_id": ["m1"],
            "outcome": ["Yes"],
            "timestamp": [pd.Timestamp("2024-01-01T00:00:00Z")],
            "price": [0.44],
        }
    )

    output = resolved_signal_row(
        row,
        timestamp=pd.Timestamp("2024-01-01T06:00:00Z"),
        include_advanced=False,
        price_history=history,
        use_historical_prices=True,
        max_price_age_hours=12,
    )

    assert output["market_probability"] == 0.44
    assert output["price_source"] == "clob_history_yes"
    assert output["is_lookahead"] is False


def test_resolved_signal_row_marks_missing_history_as_lookahead() -> None:
    output = resolved_signal_row(
        {
            "market_id": "m1",
            "question": "Will BTC close above 100k?",
            "closed_time": "2024-01-10T00:00:00Z",
            "winning_outcome": "Yes",
            "last_trade_price": 0.99,
        },
        timestamp=pd.Timestamp("2024-01-01T06:00:00Z"),
        include_advanced=False,
        price_history=pd.DataFrame(),
        use_historical_prices=True,
    )

    assert output["market_probability"] == 0.99
    assert output["price_source"] == "resolved_market_snapshot"
    assert output["is_lookahead"] is True


def test_resolved_market_active_filter_respects_dates_and_crypto() -> None:
    resolved = pd.DataFrame(
        {
            "market_id": ["m1", "m2", "m3"],
            "question": [
                "Will BTC be above 100k?",
                "Will rain happen?",
                "Will BTC hit 50k or 70k first?",
            ],
            "tags": [["crypto"], ["weather"], ["crypto"]],
            "start_date": [
                "2024-01-01T00:00:00Z",
                "2024-01-01T00:00:00Z",
                "2024-01-01T00:00:00Z",
            ],
            "closed_time": [
                "2024-01-03T00:00:00Z",
                "2024-01-03T00:00:00Z",
                "2024-01-03T00:00:00Z",
            ],
            "winning_outcome": ["Yes", "Yes", "70k"],
            "volume_num": [10, 10, 10],
        }
    )

    rows = active_resolved_market_rows(
        resolved,
        timestamp=pd.Timestamp("2024-01-02T00:00:00Z"),
        crypto_only=True,
        high_volume_only=False,
        min_volume=0,
    )

    assert [row["market_id"] for row in rows] == ["m1"]
