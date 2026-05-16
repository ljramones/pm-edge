from __future__ import annotations

from pathlib import Path

import duckdb

from execution_simulator.assumptions import run_all, trade_within_spread_rate
from execution_simulator.types import AssumptionReport, AssumptionResult


def test_run_all_returns_structured_assumption_results(archive_path: Path) -> None:
    report = run_all(archive_path)

    assert isinstance(report, AssumptionReport)
    assert {result.name for result in report.results} == {
        "top_of_book_completeness",
        "trade_within_spread_rate",
        "book_staleness_rate",
        "bid_ask_cross_rate",
        "depth_gt_1_dependency_rate",
    }
    for result in report.results:
        assert isinstance(result.empirical_value, float | type(None))
        assert isinstance(result.threshold, float)
        assert isinstance(result.passed, bool)
        assert result.note


def test_assumption_report_text_includes_pass_fail_lines() -> None:
    report = AssumptionReport(
        results=[
            AssumptionResult(
                name="example",
                empirical_value=1.0,
                threshold=0.5,
                passed=True,
                note="Example note.",
            )
        ]
    )

    text = report.to_text()

    assert "Execution simulator assumption report" in text
    assert "PASS example" in text


def test_trade_within_spread_rate_filters_stale_snapshots() -> None:
    con = duckdb.connect()
    con.execute("""
        CREATE TEMP TABLE order_book_snapshots AS
        SELECT
            'polymarket' AS venue,
            'market-1' AS market_id,
            TIMESTAMPTZ '2026-05-15 12:00:00+00' AS timestamp_utc,
            0.40 AS top_bid,
            0.60 AS top_ask
        """)
    con.execute("""
        CREATE TEMP TABLE trade_events AS
        SELECT * FROM (
            VALUES
                ('polymarket', 'market-1', TIMESTAMPTZ '2026-05-15 12:00:30+00', 0.50),
                ('polymarket', 'market-1', TIMESTAMPTZ '2026-05-15 12:00:45+00', 0.55),
                ('polymarket', 'market-1', TIMESTAMPTZ '2026-05-15 12:02:00+00', 0.90),
                ('polymarket', 'market-1', TIMESTAMPTZ '2026-05-15 12:03:00+00', 0.80)
        ) AS t(venue, market_id, timestamp_utc, price)
        """)

    filtered = trade_within_spread_rate(con, max_book_age_seconds=60)
    unfiltered = trade_within_spread_rate(con, max_book_age_seconds=99_999)

    assert filtered.empirical_value == 1.0
    assert unfiltered.empirical_value == 0.5
    assert filtered.empirical_value > unfiltered.empirical_value
    assert "total_trades=4" in filtered.note
    assert "filtered_trades=2" in filtered.note
    assert "excluded_trades=2" in filtered.note
    assert "filtered_trades=4" in unfiltered.note
