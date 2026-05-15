# pm-edge Analysis Notebooks

This directory contains exploratory notebooks for the forward-indexer parquet archive synced to the laptop.

For the full VPS-to-laptop operating model, including status-page setup and rsync cadence, see [Operations Runbook](../docs/OPERATIONS.md).

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
- Notebooks pull from `$PM_EDGE_LOCAL_FORWARD_INDEX_DIR`, the rsync destination. Paths are never hardcoded in notebook cells.
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
