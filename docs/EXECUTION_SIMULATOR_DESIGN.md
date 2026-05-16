# Execution Simulator Design

## Purpose

Reproduce, in software, what would have happened to a hypothetical order placed against historical prediction-market book state. The simulator's job is to answer one question reliably: "If I had submitted this order at this time, what would have filled, at what price, and when?"

That output is the input to all downstream strategy validation, paper trading calibration, and P&L estimation work. Without a trustworthy simulator, claims about strategy performance are claims about a fictional venue. With one, they're claims about the same venue your future capital would have traded against.

## Why now

We are building the simulator before we have enough data to validate strategies, deliberately, for three reasons:

1. **Time availability.** The weekend offers extended uninterrupted focus that won't recur during the workweek post-restructure. Building infrastructure now is the highest-leverage use of this time window.

2. **Pipeline pressure test.** Designing the simulator forces explicit specification of what trade and book features it consumes. This surfaces gaps in current data capture before they accumulate as months of unrecoverable missing fields.

3. **Sequencing logic.** Strategy validation is rate-limited by data accumulation, not by simulator readiness. If we wait until data is "enough" to start the simulator, we add weeks of delay between dataset maturity and first usable validation. Building now eliminates that bottleneck.

## What we are explicitly not doing

This document defines a v0 simulator. The following are out of scope:

- P&L reporting (no strategy logic yet - just fill simulation)
- Fee calibration (use venue-max as conservative default; refine later)
- Latency modeling (assume order arrives at simulator-time exactly; refine later)
- Queue position modeling (assume worst-case queue position; refine later)
- Partial fill resting logic across multiple book snapshots (assume immediate decision; refine later)
- Multi-leg or arbitrage execution (single-market, single-leg orders only)
- Real-time simulation (operates against historical archive only)

These are real features that will eventually matter. They are deferred because including them now would either require strategies to test against (which we don't have) or introduce parameters that can't be empirically calibrated yet (which would be guesses).

## The conservative-by-default principle

Every modeling choice that has a "more optimistic" and "more pessimistic" interpretation defaults to the pessimistic. The simulator should systematically underestimate, not overestimate, what a real trader would have achieved. Reasons:

- A pessimistic simulator that produces a strategy with positive expected value is more credible than an optimistic one that does the same.
- Live trading invariably reveals frictions that simulation missed. Starting from pessimism leaves room for upside discovery.
- The cost of an optimistic simulator is real capital loss when paper-tested assumptions don't hold. The cost of a pessimistic one is rejecting a few real strategies that would have worked. The former is much worse.

Specific defaults this implies:

- Slippage: model as full spread crossing for marketable orders
- Resting orders: assume worst-case queue position, fill only when an opposing trade clearly exceeds queue ahead
- Empty books: treat as unfillable for that snapshot, not as "the next snapshot will probably be fine"
- Stale snapshots: if the most recent book state is more than N seconds old (configurable, default 60), treat the order as failing
- Fees: assume venue-maximum taker fee for marketable, maker fee for resting

These defaults can be relaxed later, individually, with documented justification. They cannot be relaxed by tuning until results look favorable.

## Empirical grounding requirement

Every assumption the simulator makes about prediction-market data must be backed by a query against the local archive that validates the assumption is currently true (or quantifies the rate at which it is false). These assumption checks become part of the test suite.

Examples of assumptions and their validation queries:

| Assumption | Validation |
|---|---|
| Book snapshots contain top_bid and top_ask for marketable order modeling | Query: `% of snapshots with both top_bid and top_ask populated` - must be > 70% per venue |
| Trades occur at prices within the contemporaneous spread | Query: `% of trade events where trade price is between top_bid and top_ask at adjacent snapshot` - must be > 80% |
| Order book depth >1 level rarely matters for small orders | Query: `for orders <= X notional, what % require depth beyond level 1` - quantify, don't necessarily reject |
| Gap rate is low enough that snapshot interpolation isn't critical | Query: `% of 5-minute buckets with < median snapshot count` - quantify against current 21% Kalshi / 2% Polymarket |

Each assumption check produces a number. The simulator's documentation reports those numbers. If an assumption fails validation, the simulator either (a) handles the failure case explicitly in code, or (b) documents the failure mode as a known limitation.

The 41-hour data quality assessment in `RESEARCH_LOG.md` Entry 10 already documents several relevant assumptions and their current empirical validity. Use it as the starting point for the validation suite.

## Interface contract

The simulator is a Python module with this primary entry point:

```python
def simulate_order(
    market_id: str,
    venue: str,
    side: Literal["buy", "sell"],
    size: float,
    limit_price: float | None,  # None means marketable
    submitted_at: datetime,
    archive_path: Path,
    config: SimulatorConfig,
) -> FillOutcome:
    ...
```

Where `FillOutcome` includes at minimum:

- `status`: one of `filled`, `partial`, `unfilled`, `error`
- `filled_size`: actual fill size (may be < requested for partial fills)
- `filled_price`: weighted average fill price (None if no fill)
- `slippage`: filled_price minus limit_price (or vs mid for marketable)
- `time_to_fill`: duration from submitted_at to fill time (None if unfilled)
- `fees`: estimated fees paid (using venue-max default)
- `assumptions_triggered`: list of which simulator assumptions affected this outcome (for debugging and audit)

A batch function `simulate_strategy(orders: list[OrderSpec]) -> list[FillOutcome]` runs many orders sequentially against the archive, producing a fill log usable for downstream analysis.

## Module location

`src/execution_simulator/` as a new top-level module. Sibling to `src/data/`. The simulator is a consumer of the data archive, not part of the data pipeline.

```text
src/execution_simulator/
├── __init__.py
├── config.py          # SimulatorConfig with conservative defaults
├── types.py           # OrderSpec, FillOutcome, etc.
├── fill_logic.py      # The actual modeling
├── book_lookup.py     # Efficient point-in-time book state retrieval from archive
├── assumptions.py     # Validation queries that run against archive
└── simulate.py        # The public simulate_order and simulate_strategy entry points
```

Tests in `tests/test_execution_simulator/` with parallel structure.

## Calibration discipline

The simulator must not be tuned to make any specific strategy look better. The single biggest risk of pre-strategy simulator construction is unconscious optimization for favorable backtest results.

Defense:

1. Define conservative defaults before testing against any strategy.
2. Lock those defaults in `config.py` with a clear comment block: "These values are conservative-by-design. They may be relaxed only with documented justification, never to improve backtest results."
3. Any future relaxation requires (a) an empirical justification based on live trading data, paper trading evidence, or new validation queries, and (b) a `git commit` message that states the relaxation explicitly.
4. The validation query results from the assumption suite are reported alongside any backtest output, so reviewers can see what the simulator assumed and whether assumptions held.

## v0 acceptance criteria

The simulator is "v0 complete" when:

1. The module structure above exists with all files populated (some may be skeletons).
2. `simulate_order` and `simulate_strategy` work end-to-end against the current local archive.
3. The conservative-by-default principle is implemented in all modeling choices.
4. The assumption validation suite has at least 5 checks, each tied to a specific simulator assumption.
5. Test coverage includes at least:
   - Marketable order in a normal book -> fills at top of opposing side
   - Marketable order in an empty book -> status = `unfilled`
   - Resting order at limit_price worse than top -> status = `unfilled` (worst-case queue assumption means it doesn't fill in v0)
   - Resting order at limit_price better than top -> undefined behavior; explicitly raise or document
   - Stale book state (> 60s old) -> status = `unfilled`
   - Batch of 10 orders against real archive data -> produces 10 fill outcomes without error
6. Documentation in `docs/EXECUTION_SIMULATOR.md` (separate from this design doc - that one is the user manual) explains how to use the simulator, what assumptions it makes, and what its known limitations are.

The simulator is not required at v0 to:

- Match any specific strategy's expected performance
- Handle every edge case
- Model fees with venue-specific precision
- Operate on streaming data

Those are post-v0 work.

## What v1 looks like (out of scope for this weekend)

Once v0 is operational and a few weeks of additional data have accumulated, v1 work includes:

- Realistic queue position modeling using observed fill rates by depth level
- Fee model calibrated against actual Polymarket and Kalshi fee schedules including maker rebates
- Partial fill resting logic across multiple snapshots
- Latency simulation based on observed WebSocket-to-trade timestamps
- Slippage refinement against trade-level data (using the new trade IDs)
- Walk-forward validation harness for backtests

These belong in a separate design doc when they become relevant. Don't pre-build them.
