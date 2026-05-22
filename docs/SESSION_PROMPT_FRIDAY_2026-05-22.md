# Friday Resume Session - pm-edge Week-of-Accumulation Validation

## Context

I paused active work on pm-edge on Sunday May 17, 2026 after a 9+ hour session that included substantial production fixes: Kalshi parser, false-positive filter, graceful shutdown, async batching, lag fix for both Kalshi and Polymarket via Gamma API, and four research log entries, Entries 19-22. The system has been running unattended on a DigitalOcean VPS for 5 days, collecting clean post-fix data. The external drive was ejected for the week; cron skips rsync cleanly when the volume is unmounted.

Today is Friday and I am reattaching the drive to do the first real research session on clean accumulated data.

## Phase 1: Operational Verification (15-20 min)

Walk me through these checks. After each, if anything is unexpected, stop and surface it before continuing.

### 1.1 Reattach Drive And Force A Manual Rsync

```bash
# After physically reattaching the external drive
diskutil list | grep pm-edge-archive

PM_EDGE_VPS_HOST="pmedge@165.245.235.75" \
PM_EDGE_LOCAL_FORWARD_INDEX_DIR="/Volumes/pm-edge-archive/pm-edge-data/forward_index" \
PM_EDGE_LOCAL_RESOLVED_DIR="/Volumes/pm-edge-archive/pm-edge-data/resolved_market_outcomes" \
/bin/bash ~/ML/pm-edge/deploy/forward_indexer/rsync_to_laptop.sh
```

Expected:

- Both directories sync without errors.
- `forward_index` size grows substantially; it was 1.2 GB Sunday, expect 5-7 GB Friday.
- `resolved_market_outcomes/` has new parquet files.

### 1.2 VPS Health Check

```bash
ssh pmedge@165.245.235.75 'echo "=== uptime ===" && uptime && echo "=== memory ===" && free -m && echo "=== disk ===" && df -h /opt/pm-edge && echo "=== watcher ===" && sudo systemctl status resolution-watcher --no-pager | head -10 && echo "=== indexer ===" && sudo systemctl status forward-indexer --no-pager | head -10'
```

Expected:

- Both services active.
- Memory under 60%, with new 400M/600M cap well within bounds.
- Disk usage under 20%; it was 13% Sunday.
- Recent watcher restart not visible; uptime should be near 5 days.

If watcher restarted unexpectedly, check journal:

```bash
ssh pmedge@165.245.235.75 'sudo journalctl -u resolution-watcher --since "5 days ago" --no-pager | grep -E "Started|Stopped|OOM|MemoryHigh" | tail -20'
```

### 1.3 Check Cron Behavior Over The Week

```bash
tail -100 ~/pm-edge-data/rsync.log
```

Expected:

- 5 cron runs, all showing "External volume ... is not mounted. Skipping rsync."
- No rsync attempts to internal disk.
- No error spam.

If actual rsync runs wrote to wrong locations, the mount-check has a bug that needs investigation before proceeding.

### 1.4 Validate Week-Of-Data Quality

```bash
sudo /opt/pm-edge/.venv/bin/python <<'PYEOF'
import duckdb

con = duckdb.connect()

print("=== Capture totals ===")
con.sql("""
SELECT
    venue,
    COUNT(*) AS total_resolutions,
    SUM(CASE WHEN venue_resolved_at_utc IS NOT NULL THEN 1 ELSE 0 END) AS with_resolution_ts,
    SUM(CASE WHEN venue_resolved_at_utc IS NOT NULL AND final_snapshot_timestamp_utc IS NOT NULL THEN 1 ELSE 0 END) AS with_book_state,
    MIN(resolution_timestamp_utc) AS earliest,
    MAX(resolution_timestamp_utc) AS latest
FROM read_parquet('/opt/pm-edge/data/raw/resolved_market_outcomes/**/*.parquet', union_by_name=true)
GROUP BY venue
""").show()

print("\n=== Lag validation: negative-lag rows should be 0 ===")
con.sql("""
SELECT
    venue,
    COUNT(*) AS total_with_both,
    SUM(CASE WHEN final_snapshot_timestamp_utc > venue_resolved_at_utc + INTERVAL 5 SECOND THEN 1 ELSE 0 END) AS negative_lag_violations,
    AVG(EXTRACT(EPOCH FROM (venue_resolved_at_utc - final_snapshot_timestamp_utc))) / 60 AS avg_lag_minutes
FROM read_parquet('/opt/pm-edge/data/raw/resolved_market_outcomes/**/*.parquet', union_by_name=true)
WHERE venue_resolved_at_utc IS NOT NULL AND final_snapshot_timestamp_utc IS NOT NULL
GROUP BY venue
""").show()

print("\n=== Forward index health ===")
con.sql("""
SELECT
    venue,
    COUNT(*) AS snapshots,
    COUNT(DISTINCT market_id) AS unique_markets,
    MIN(timestamp_utc) AS earliest,
    MAX(timestamp_utc) AS latest
FROM read_parquet('/opt/pm-edge/data/raw/forward_index/order_book_snapshots/**/*.parquet', union_by_name=true)
WHERE timestamp_utc > NOW() - INTERVAL '6 days'
GROUP BY venue
""").show()
PYEOF
```

Expected:

- Total resolutions: 500-1500 per venue, roughly 5x the Sunday count of about 141 Kalshi plus 52 Polymarket.
- Polymarket `with_resolution_ts` substantially populated because the Gamma fix has been active all week.
- `negative_lag_violations = 0` for both venues. This validates that the lag fix worked in production over a full week.
- Forward index: millions of snapshots across thousands of markets.

Stop here and report results before continuing to research. If `negative_lag_violations > 0` anywhere, investigate that regression. If totals are far below expectations, diagnose capture quality before analysis.

## Phase 2: Research Re-Run On Clean Data (60-90 min)

The Sunday analyses produced results on contaminated or small data. Re-run on clean week-of-data.

### 2.1 Volatility-Signal Hypothesis, Entry 22 Follow-Up

Pre-registered test. Sunday showed AIC improvement of 5.13 with LRT p=0.008 at n=35. Does it survive at n>=200?

Use the Entry 22 notebook section as the template. Add the new run as a clearly labeled separate analysis; do not overwrite the Sunday result.

Regression:

- Model 1 baseline: `outcome ~ mid_final`
- Model 4 plus volatility: `outcome ~ mid_final + volatility`
- Look for AIC delta, LRT p-value, volatility coefficient sign and significance.

Pre-registered decision:

- AIC delta > 2 to survive.
- p < 0.05 to maintain significance.
- If results do not survive, the hypothesis was overfitting to small sample.
- If results survive, it is a real signal worth investigating further.

### 2.2 Category-Segmented Calibration With Proper Polymarket Coverage

Sunday's Entry 20 showed only Kalshi data because Polymarket lacked book state. With the week's Polymarket captures, now Gamma-anchored, run the first real Polymarket calibration analysis.

Look for:

- Polymarket Brier score by category.
- Politics/news versus sports versus crypto versus other on Polymarket.
- Polymarket sports versus Kalshi MLB: do similar event types show different efficiency by venue?
- Any category with more than 30 markets showing systematic mispricing.

### 2.3 Eurovision-Style Cultural Events Follow-Up

Entry 20 hinted at Eurovision underpriced favorites at n=7. Check whether any cultural markets resolved this week, such as Cannes or reality TV finales.

If a cultural category has n>=15 and shows the same positive gap, that is the first real signal worth pursuing.

### 2.4 Pre-Resolution Time-Horizon Calibration

Sunday's analyses used the snapshot closest to resolution. With a week of data, compute calibration at multiple horizons:

- T-15 min before resolution.
- T-1 hour.
- T-6 hours.
- T-24 hours.

Hypothesis: markets are well-calibrated near resolution but may be poorly calibrated 6-24 hours out. If true, the place to find edge is in earlier windows.

This is the most data-intensive analysis and may need to be split across multiple agent calls.

## Phase 3: Documentation (15 min)

After Phase 2 produces results, add research log entries:

- Entry 23: Lag fix validation over 5 days of production data.
- Entry 24: Volatility-signal re-test result, survival or null.
- Entry 25: First real Polymarket calibration.
- Entry 26: Time-horizon calibration, if completed.

Each entry follows the Entry 19-22 format: hypothesis, method, results table, honest interpretation, caveats, and next questions.

## Phase 4: Pending P0 If Reaching For Execution Simulator

Skip if just doing analysis.

External code reviewer identified that `src/execution_simulator/fill_logic.py` raises `ValueError` on resting limit orders that improve on touch. This blocks any maker-side strategy backtest. If today's session reaches the point of actually running strategies through the simulator, fix this first.

Quick fix prompt template; do not execute yet:

> Modify `fill_logic.py:42` and `:61` to return `_unfilled(market_id, "resting_order_queue_unmodeled")` instead of raising ValueError. Add a test for the resting-order case. Document the limitation that queue position is unmodeled in the simulator README.

## Explicitly Out Of Scope For This Friday Session

- Phase 3 metadata-only watch list.
- Parquet compaction job.
- Re-processing the 233 archived pre-fix captures.
- Kalshi signed-WebSocket authentication, Phase 1.5.
- Multi-outcome resolution support.
- Dispute/clarification handling for already-resolved markets.
- Dedup ceiling investigation.

These reviewer-identified improvements do not block today's research goal: first real strategy validation on clean data.

## Energy Expectation

Today's session is lighter than Sunday's. Most of the work is interpretation, not building. The system has been running unattended for 5 days; the goal is to ask questions of accumulated data, not change the system.

If a research analysis produces a surprising result, question whether it is a real signal or a methodology artifact before getting excited. Apply the same critical lens that exposed the Entry 19 lag artifact.

## Session Start

Begin with Phase 1.1: reattach the drive and run manual rsync. Do not run anything else until that completes successfully. Report results before continuing.
