# Execution Simulator

## Purpose

The execution simulator replays hypothetical single-market orders against the
captured forward-index parquet archive. It answers one narrow question: if an
order had been submitted at a specific timestamp, what would have filled, at
what price, and under which simulator assumptions?

The simulator is conservative by default. It is suitable for checking order-fill
mechanics and shaping the execution-simulator input contract. It is not yet a
complete strategy backtester.

## Quick Start

```python
from datetime import UTC, datetime
from pathlib import Path

from execution_simulator import SimulatorConfig, simulate_order

outcome = simulate_order(
    market_id="example-market-id",
    venue="polymarket",
    side="buy",
    size=10.0,
    limit_price=None,
    submitted_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
    archive_path=Path("~/pm-edge-data/forward_index").expanduser(),
    config=SimulatorConfig(),
)

print(outcome.to_dict())
```

Batch simulation uses `OrderSpec` objects:

```python
from execution_simulator import OrderSpec, simulate_strategy

orders = [
    OrderSpec(
        market_id="example-market-id",
        venue="polymarket",
        side="buy",
        size=10.0,
        limit_price=None,
        submitted_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
    )
]

outcomes = simulate_strategy(
    orders,
    archive_path=Path("~/pm-edge-data/forward_index").expanduser(),
)
```

`simulate_strategy()` prints the assumption validation report before returning
fill outcomes.

## Interface

`OrderSpec` fields:

- `market_id`: venue market identifier.
- `venue`: `polymarket` or `kalshi`.
- `side`: `buy` or `sell`.
- `size`: requested contract size.
- `limit_price`: limit price in dollar probability units. `None` means
  marketable.
- `submitted_at`: historical submission timestamp.

`FillOutcome` fields:

- `status`: `filled`, `partial`, `unfilled`, or `error`.
- `requested_size`: original order size.
- `filled_size`: simulated filled size.
- `filled_price`: weighted average fill price, or `None` when unfilled.
- `slippage`: filled price minus the limit price, or minus mid for marketable
  orders.
- `time_to_fill`: zero for immediate fills in v0, `None` when unfilled.
- `fees`: estimated taker or maker fees. v0 only fills marketable orders.
- `assumptions_triggered`: audit trail of simulator assumptions that affected
  the outcome.

`SimulatorConfig` defaults:

- `max_book_age_seconds = 60`
- `taker_fee_bps = 50`
- `maker_fee_bps = 0`
- `allow_resting_fills = False`
- `slippage_model = "full_spread"`
- `require_complete_top_book = True`

These defaults are conservative by design. They can be relaxed only with
documented empirical justification.

## Fill Logic

v0 uses the latest book snapshot for the target `(venue, market_id)` at or
before `submitted_at`.

Marketable orders fill against the opposing top of book. If the top level has
enough size, the order fills completely. If the top level has less size than
requested, v0 returns a partial fill and does not walk deeper levels.

Resting orders do not fill by default. This represents worst-case queue
position. Queue modeling is v1 work.

Empty or stale books produce `unfilled` outcomes. The simulator does not impute
missing book state from later snapshots.

## Assumption Validation

Run all assumption checks directly:

```python
from pathlib import Path

from execution_simulator.assumptions import run_all

report = run_all(Path("~/pm-edge-data/forward_index").expanduser())
print(report.to_text())
```

The suite reports:

- Top-of-book completeness per archive.
- Trade-within-spread rate.
- Book staleness rate.
- Bid-ask cross rate.
- Depth greater than level 1 dependency rate.

The report is an operational warning surface, not a pass that validates
strategy performance. Failed checks mean the simulator either handled a failure
case pessimistically or the data is not suitable for the intended analysis.

## Known Limitations

v0 does not implement:

- P&L reporting.
- Strategy logic.
- Venue-specific fee precision.
- Latency modeling.
- Queue position modeling.
- Partial-fill resting logic across later snapshots.
- Depth walking beyond level 1.
- Multi-leg execution.
- Real-time simulation.

The simulator operates only against historical forward-index parquet data.

## When To Trust v0

Trust v0 for:

- Verifying that the archive supports point-in-time book lookup.
- Testing whether hypothetical marketable orders have enough visible top-level
  liquidity.
- Designing downstream fill-log schemas.
- Identifying data-quality assumptions that need stronger capture or validation.

Do not trust v0 for:

- Final strategy P&L.
- Maker strategy economics.
- Resting-order fill rates.
- Latency-sensitive tactics.
- Claims that require depth beyond the first book level.

Those require v1 calibration against additional forward data and, eventually,
paper-trading evidence.
