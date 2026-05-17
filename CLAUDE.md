# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project shape

pm-edge is a Python 3.11+, async-first research/paper-trading system for Polymarket and Kalshi. It is intentionally **paper-only** — no live-money execution path exists, and adding one is out of scope unless explicitly requested.

The repo is currently in a transition: the legacy Phase 0-14 modules (signal generation, deep backtester, edge detector, fear/liquidity/structural strategies) are retained as research artifacts but **must not be used for strategy approval**. Real validation now depends on the forward data layer (Phase 1, deployed) plus the in-progress execution simulator. See `docs/DATA_QUALITY_LESSONS.md` for why legacy `signals_*.parquet` results are rejected.

## Common commands

Quality gates (run before any commit; the same set is enforced via pre-commit and CI assumptions):

```bash
pytest
ruff check .
black --check .
ruff format --check .
mypy src scripts
```

Run one test file or test:

```bash
pytest tests/test_forward_indexer.py
pytest tests/test_forward_indexer.py::test_specific_case -x
pytest -k "expression"
```

Install editable with dev/analysis extras:

```bash
uv pip install -e ".[dev]"          # core dev + tests
uv pip install -e ".[analysis]"      # adds duckdb, jupyter, plotting
```

Notebook env: notebooks read from `$PM_EDGE_LOCAL_FORWARD_INDEX_DIR` via DuckDB; don't hardcode archive paths. Use helpers in `notebooks/lib/queries.py` and `notebooks/lib/plots.py`. End every notebook with a `Findings` section and update `notebooks/INDEX.md` after a session.

## Architecture orientation

Two largely independent data flows live in this repo. Don't confuse them:

**1. Forward data layer (current, authoritative).** Producer is `scripts/forward_index.py` running on a DigitalOcean VPS under systemd; consumer is the laptop via `deploy/forward_indexer/rsync_to_laptop.sh` and DuckDB notebooks.

```
Polymarket Gamma + CLOB WS / Kalshi REST
  → src/data/forward_indexer/ (discovery, filters, BookState, runner, BufferedParquetWriter)
  → data/raw/forward_index/{order_book_snapshots,trade_events,market_metadata_snapshots}/venue=…/date=…/*.parquet
  → rsync → laptop archive → DuckDB (notebooks/lib/queries.py)
```

Companion consumer: `src/data/resolution_watcher/` reads the forward archive + venue market endpoints and writes `resolved_market_outcomes` parquet. The execution simulator (`src/execution_simulator/`) consumes captured book snapshots to produce realistic fills against historical resting quotes — this is the validation path that will eventually replace legacy backtests.

**2. Legacy research flow (frozen).** `scripts/generate_signals.py` → flat parquet → `scripts/deep_backtest.py` → `scripts/generate_report.py`. The signal pipeline, edge detector (`src/strategies/edge_detector.py`), Kelly allocator (`src/execution/portfolio.py`), hardened risk engine (`src/execution/risk_engine.py`), fear/liquidity/structural strategies, deep analysis, and live paper trader (`scripts/live_paper.py`) all sit on this side. Touching them is fine for cleanup or bug fixes, but new strategy conclusions from this flow are not valid.

The `src/` layout maps directly to responsibility (`core/`, `data/`, `features/`, `models/`, `strategies/`, `execution/`, `execution_simulator/`, `backtesting/`, `monitoring/`, `utils/`). Discoverable enough — read `docs/TECHNICAL_OVERVIEW.md` for the full module-by-module walkthrough.

## Configuration

All settings load through `src/core/config.py` (Pydantic v2 + `pydantic-settings`) with the `PM_EDGE_` env prefix. Local default is SQLite at `data/pm_edge.db`. LLM defaults to local Ollama (`qwen2.5:32b`). See `.env.example` for the full surface.

Laptop-side env that notebooks and rsync expect:

```bash
PM_EDGE_VPS_HOST=pmedge@<vps-ip>
PM_EDGE_LOCAL_FORWARD_INDEX_DIR=$HOME/pm-edge-data/forward_index
PM_EDGE_LOCAL_RESOLVED_DIR=$HOME/pm-edge-data/resolved_market_outcomes
```

`rsync_data.sh` at the repo root is a thin wrapper that targets `/Volumes/pm-edge-archive/…`; the rsync script no-ops cleanly when that external drive is unmounted rather than silently filling the internal disk.

## Style and conventions

- Line length 100 (black + ruff). Ruff lint set: `E, F, I, B, C4, SIM, UP, ASYNC`, `E501` ignored. `mypy` runs with `disallow_untyped_defs` and the pydantic plugin.
- pytest config: `asyncio_mode = "auto"`, `pythonpath = ["src", "."]`, `testpaths = ["tests"]`. Tests import from `src/` modules without the `src.` prefix (e.g. `from data.forward_indexer ...`).
- `data/` is gitignored. Never commit captured parquet, raw venue dumps, model artifacts, or `.env`.
- Don't run notebooks on the VPS; don't point laptop notebooks at `/opt/pm-edge` over SSHFS.
- Don't change forward-indexer discovery filters during an active analysis window without recording the date and reason — filter changes invalidate cross-window comparisons.

## Key references

- `README.md` — phase history and CLI examples.
- `docs/TECHNICAL_OVERVIEW.md` — full architecture.
- `docs/OPERATIONS.md` — VPS producer, rsync, notebook daily/weekly loops.
- `docs/forward_indexer.md` — producer details and failure modes.
- `docs/resolution_watcher.md` — resolution-detection consumer.
- `docs/EXECUTION_SIMULATOR_DESIGN.md` / `EXECUTION_SIMULATOR.md` — simulator design and usage.
- `docs/DATA_QUALITY_LESSONS.md` — why legacy signals are rejected (read this before reaching for `signals_*.parquet`).
- `docs/RESEARCH_LOG.md` — append-only hypothesis/decision log; never edit prior entries except to mark resolved/refuted/superseded.
