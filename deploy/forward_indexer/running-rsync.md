# Running Rsync

This note documents the current laptop sync workflow for pulling forward-indexer parquet
and resolution outcomes from the VPS into the local analysis archive.

## Current Script Behavior

`deploy/forward_indexer/rsync_to_laptop.sh` uses:

```bash
rsync -avz --partial -e "ssh -i ~/.ssh/pm_edge_rsync" \
  "${VPS_HOST}:${REMOTE_FORWARD_INDEX_DIR}" \
  "${LOCAL_FORWARD_INDEX_DIR}"

rsync -avz --partial -e "ssh -i ~/.ssh/pm_edge_rsync" \
  "${VPS_HOST}:${REMOTE_RESOLVED_DIR}" \
  "${LOCAL_RESOLVED_DIR}"
```

The script does not use `--ignore-existing`. Rsync's normal archive-mode size and mtime checks avoid recopying unchanged parquet parts while still repairing interrupted or partial local files on a later run.

## Mount Safety

When either local destination is under `/Volumes/`, the script verifies that the named volume is mounted before creating destination directories or running rsync. If the external drive is ejected:

- The script exits `0` with an informational message.
- Cron does not trigger an error email.
- The next sync after reattaching the drive proceeds normally.

This prevents the failure mode where `/Volumes/pm-edge-archive/` is created as a regular directory on the laptop's internal disk and data is silently synced there.

Manual verification scenarios:

```bash
# Relative or non-/Volumes destination: check is a no-op.
PM_EDGE_VPS_HOST="pmedge@<ip>" \
PM_EDGE_LOCAL_FORWARD_INDEX_DIR="data/raw/forward_index" \
PM_EDGE_LOCAL_RESOLVED_DIR="data/raw/resolved_market_outcomes" \
bash -n deploy/forward_indexer/rsync_to_laptop.sh

# Missing external volume: exits 0 before mkdir or rsync.
PM_EDGE_VPS_HOST="pmedge@<ip>" \
PM_EDGE_LOCAL_FORWARD_INDEX_DIR="/Volumes/DefinitelyMissingPmEdgeVolume/forward_index" \
PM_EDGE_LOCAL_RESOLVED_DIR="/Volumes/DefinitelyMissingPmEdgeVolume/resolved_market_outcomes" \
bash deploy/forward_indexer/rsync_to_laptop.sh

# Mounted external volume: proceeds to normal rsync behavior.
PM_EDGE_VPS_HOST="pmedge@<ip>" \
PM_EDGE_LOCAL_FORWARD_INDEX_DIR="/Volumes/pm-edge-archive/pm-edge-data/forward_index" \
PM_EDGE_LOCAL_RESOLVED_DIR="/Volumes/pm-edge-archive/pm-edge-data/resolved_market_outcomes" \
bash deploy/forward_indexer/rsync_to_laptop.sh
```

The script reads these environment variables:

- `PM_EDGE_VPS_HOST`: required, for example `pmedge@<droplet-ip>`.
- `PM_EDGE_REMOTE_FORWARD_INDEX_DIR`: optional, defaults to `/opt/pm-edge/data/raw/forward_index/`.
- `PM_EDGE_REMOTE_RESOLVED_DIR`: optional, defaults to `/opt/pm-edge/data/raw/resolved_market_outcomes/`.
- `PM_EDGE_LOCAL_FORWARD_INDEX_DIR`: optional, defaults to `data/raw/forward_index/` relative to the current working directory.
- `PM_EDGE_LOCAL_RESOLVED_DIR`: optional, defaults to a sibling `resolved_market_outcomes/` directory next to `PM_EDGE_LOCAL_FORWARD_INDEX_DIR`.

For the laptop workflow, set an absolute local destination:

```bash
export PM_EDGE_VPS_HOST="pmedge@<your-vps-ip>"
export PM_EDGE_LOCAL_FORWARD_INDEX_DIR="$HOME/pm-edge-data/forward_index"
export PM_EDGE_LOCAL_RESOLVED_DIR="$HOME/pm-edge-data/resolved_market_outcomes"
```

## First Run

Run a dry run first:

```bash
rsync -avzn --partial -e "ssh -i ~/.ssh/pm_edge_rsync" \
  "${PM_EDGE_VPS_HOST}:${PM_EDGE_REMOTE_FORWARD_INDEX_DIR:-/opt/pm-edge/data/raw/forward_index/}" \
  "${PM_EDGE_LOCAL_FORWARD_INDEX_DIR:-data/raw/forward_index/}"
```

Then run the script:

```bash
bash deploy/forward_indexer/rsync_to_laptop.sh
```

## Verify

```bash
du -sh "$PM_EDGE_LOCAL_FORWARD_INDEX_DIR"
du -sh "$PM_EDGE_LOCAL_RESOLVED_DIR"
ls "$PM_EDGE_LOCAL_FORWARD_INDEX_DIR"
ls "$PM_EDGE_LOCAL_RESOLVED_DIR"
```

Expected table directories:

```text
order_book_snapshots/
trade_events/
market_metadata_snapshots/
```

Expected resolution-output directories:

```text
venue=kalshi/
venue=polymarket/
```

DuckDB sanity check:

```bash
duckdb -c "SELECT venue, COUNT(*) FROM read_parquet('$PM_EDGE_LOCAL_FORWARD_INDEX_DIR/order_book_snapshots/**/*.parquet') GROUP BY venue"
```

## Cron

macOS cron does not inherit the interactive shell environment. Put the required environment values directly in the crontab entry or wrap them in a local shell script.

Example daily pull:

```cron
0 9 * * * PM_EDGE_VPS_HOST="pmedge@<ip>" PM_EDGE_LOCAL_FORWARD_INDEX_DIR="$HOME/pm-edge-data/forward_index" PM_EDGE_LOCAL_RESOLVED_DIR="$HOME/pm-edge-data/resolved_market_outcomes" /bin/bash /Users/larrymitchell/ML/pm-edge/deploy/forward_indexer/rsync_to_laptop.sh >> "$HOME/pm-edge-data/rsync.log" 2>&1
```

Use the real checkout path on the laptop if it differs from `/Users/larrymitchell/ML/pm-edge`.
