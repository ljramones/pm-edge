# pm-edge Analysis Notebooks

This directory contains exploratory notebooks for the forward-indexer parquet archive synced to the laptop.

For the full VPS-to-laptop operating model, including status-page setup and rsync cadence, see [Operations Runbook](../docs/OPERATIONS.md).

## What These Notebooks Are For

The notebooks are the human inspection layer for the forward-indexer data. The indexer records public market data into parquet files; the notebooks read those files through DuckDB and help answer basic questions before any strategy research starts:

- Is the capture process still running?
- Are Polymarket and Kalshi both producing usable rows?
- Are books valid, non-empty, and changing over time?
- Are there gaps, duplicates, or stale markets?
- Which markets have enough continuous data to be worth analyzing?

The notebooks are not execution systems. They do not place trades, call venue APIs, or mutate the parquet archive. They are meant to be rerun after each laptop rsync cycle.

## Notebook Map

- `2026-05-22-first-look.ipynb`: first-pass health and data-quality notebook for the forward archive. Start here after each fresh rsync.
- `phase1_exploration.ipynb`: older Phase 1 feature-engineering demonstration using synthetic/demo objects.
- `backtest_analysis.ipynb`: older signal-backtest template.
- `portfolio_analysis.ipynb`: older portfolio-backtest template.
- `advanced_features_exploration.ipynb`: older legacy-signal feature exploration template.
- `deep_backtest_analysis.ipynb`: older deep-backtest artifact inspection template.

The older notebooks remain useful for understanding historical research tooling, but the current validation path starts with `2026-05-22-first-look.ipynb` and forward-captured parquet.

## Metric Glossary

- **Snapshot:** one captured order-book observation for one market at one timestamp.
- **Snapshot source:** whether a row came from REST initialization/refresh or a WebSocket-maintained book state.
- **Freshness:** how old the latest snapshot is. A stale latest snapshot means capture or rsync has stopped.
- **Gap:** a time bucket where snapshot count is materially below that venue's normal count.
- **Top bid / top ask:** best available bid and ask in the captured book.
- **Spread:** `top_ask - top_bid`. Tight spreads indicate more tradeable markets.
- **Book validity:** checks for impossible or suspicious states such as crossed books, prices outside `[0, 1]`, missing levels, or non-positive spreads.
- **Depth:** summed size across captured bid or ask levels. More depth means the book can absorb larger trades.
- **Movement:** number of distinct observed top bids/asks. A market with no movement can be stable, stale, or not receiving live updates.
- **Trade overview:** captured trades by venue, market count, contracts, notional, and duplicate trade IDs.
- **Metadata universe:** market metadata coverage, status mix, volume/liquidity distribution, and time-to-close.
- **Analysis readiness:** a conservative screen for markets with enough snapshots, movement, spread quality, and both-sided books to inspect further.

## Naming

Notebook filenames use:

```text
YYYY-MM-DD-short-topic.ipynb
```

Examples:

- `2026-05-22-first-look.ipynb`
- `2026-06-03-polymarket-overnight-spreads.ipynb`

## Conventions

- Every notebook starts by importing from `notebooks.lib.queries` and `notebooks.lib.plots`.
- Every notebook ends with a `Findings` markdown cell summarizing what was learned, including when no useful pattern was found.
- `INDEX.md` is updated at the end of each notebook session with one line: filename, topic, key finding or conclusion.
- Notebooks pull from `$PM_EDGE_LOCAL_FORWARD_INDEX_DIR`, the rsync destination. Notebook cells do not hardcode query paths. A notebook may use `os.environ.setdefault(...)` to provide a local fallback, but it must not overwrite an already configured environment variable.
- DuckDB queries stay time-bounded for performance. Filter by `timestamp_utc` ranges when querying large tables.
- Plots default to Plotly for interactivity. Matplotlib is used only when static export is needed.

## Local Setup

Install the analysis extras:

```bash
uv pip install -e '.[analysis]'
```

Point the notebooks at the local rsync destination:

```bash
export PM_EDGE_LOCAL_FORWARD_INDEX_DIR="$HOME/pm-edge-data/forward_index"
```

Start JupyterLab:

```bash
jupyter lab notebooks/
```
