**What the script does**

- Uses three env vars with sensible defaults
- Creates the local directory if missing
- Uses `rsync -avz --partial --ignore-existing`
  - `-a` = archive mode (preserves timestamps, permissions, recursion)
  - `-v` = verbose
  - `-z` = compress in transit
  - `--partial` = keep partially-transferred files if rsync is interrupted, resume from there next time
  - `--ignore-existing` = skip files that already exist on the destination

**The one flag worth thinking about: `--ignore-existing`**

This skips any file that already exists at the destination, regardless of whether the VPS version has changed. For a write-once-then-immutable parquet pattern (which is how most streaming indexers work — flush batch to a new file, never modify it), this is fine and efficient.

But it has one failure mode: if rsync runs while the indexer is mid-flush on a parquet file, you transfer the partial file. Next time rsync runs, `--ignore-existing` skips it because it already exists locally, even though the VPS version is now complete. You end up with a permanently truncated file locally.

Two options:

1. **Drop `--ignore-existing`.** rsync's default with `-a` uses size and mtime to detect changes — it won't re-transfer unchanged files, so you keep the efficiency, but you also pick up any files that changed size since last sync. This is the safer default for archive workflows.

2. **Keep `--ignore-existing` and add a periodic full-sync.** Once a week or so, drop the flag for one run to catch any partial files that got stuck. More complex, not really worth the cognitive overhead.

I'd recommend option 1. Edit the script:

```bash
rsync -avz --partial \
  "${VPS_HOST}:${REMOTE_DIR}" \
  "${LOCAL_DIR}"
```

Or override at runtime with an env var passthrough, but a script edit is cleaner. Commit it back to the repo.

**Configure your env**

The script requires `PM_EDGE_VPS_HOST` and you'll want to set `PM_EDGE_LOCAL_FORWARD_INDEX_DIR` to an absolute path (otherwise it lands wherever you run the script from, which is a footgun).

Add to your `~/.zshrc`:

```bash
export PM_EDGE_VPS_HOST="pmedge@<your-vps-ip>"
export PM_EDGE_LOCAL_FORWARD_INDEX_DIR="$HOME/pm-edge-data"
```

Then `source ~/.zshrc` (or open a new terminal).

**First run — dry run, then real**

Always do a dry run first to confirm what's about to happen:

```bash
# Dry run: shows what would be transferred without doing it
rsync -avzn --partial \
  "${PM_EDGE_VPS_HOST}:/opt/pm-edge/data/raw/forward_index/" \
  "${PM_EDGE_LOCAL_FORWARD_INDEX_DIR}/"
```

The `-n` flag makes it a no-op simulation. You'll see a list of files that would transfer plus total size. For the first run this is your entire ~269 MB.

If that looks right, run for real:

```bash
bash ~/pm-edge/deploy/forward_indexer/rsync_to_laptop.sh
```

**Verify**

```bash
du -sh "$PM_EDGE_LOCAL_FORWARD_INDEX_DIR"
ls "$PM_EDGE_LOCAL_FORWARD_INDEX_DIR"
```

You should see `order_book_snapshots/`, `trade_events/`, `market_metadata_snapshots/` directories, with sizes roughly matching what's on the VPS.

Then a DuckDB sanity check against the local copy:

```bash
duckdb -c "SELECT venue, COUNT(*) FROM read_parquet('$PM_EDGE_LOCAL_FORWARD_INDEX_DIR/order_book_snapshots/**/*.parquet') GROUP BY venue"
```

Should return Polymarket ~1.5M, Kalshi ~10k. Same numbers as the VPS query.

**Cron for daily**

Once the manual run works, add to your laptop's crontab:

```bash
crontab -e
```

Add:

```
0 9 * * * /bin/bash /Users/larry/pm-edge/deploy/forward_indexer/rsync_to_laptop.sh >> /Users/larry/pm-edge-data/rsync.log 2>&1
```

That's 9 AM daily, when your laptop is reliably awake. You can pick any time you prefer.

Note: cron jobs on macOS need full paths for binaries and don't inherit your shell env. The env vars `PM_EDGE_VPS_HOST` and `PM_EDGE_LOCAL_FORWARD_INDEX_DIR` need to be available to the cron'd process. Two ways:

1. Set them inside the script itself (less flexible)
2. Set them in the crontab entry:

```
0 9 * * * export PM_EDGE_VPS_HOST="pmedge@<ip>" PM_EDGE_LOCAL_FORWARD_INDEX_DIR="/Users/larry/pm-edge-data" && /bin/bash /Users/larry/pm-edge/deploy/forward_indexer/rsync_to_laptop.sh >> /Users/larry/pm-edge-data/rsync.log 2>&1
```

Less elegant but explicit and works.

**Summary of what to do right now**

1. Edit the script to drop `--ignore-existing`
2. Commit the change
3. Set env vars in `~/.zshrc`
4. Dry-run from the laptop
5. Real run
6. Verify with DuckDB
7. Add the cron entry

About 15 minutes total. Then you have a working pipeline that accumulates clean data on your laptop daily until the external drive arrives May 20.