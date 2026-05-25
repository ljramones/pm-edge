# Experiment 2 — Near-Resolution Capture: Deploy & Monitor Runbook
_Created 2026-05-24. Supervised rollout of a memory-risky capture change on a box
with an OOM/thrash history. Do NOT deploy-and-walk-away. Stay on the box for the
first full near-resolution window at each settings tier._

## Why this runbook exists

The near-resolution capture mode increases write volume and snapshot count with
dedup disabled — on the forward indexer, the subsystem that OOM-killed once and
that thrashed the box to load 15 this week. This is exactly the kind of change
that spikes memory. The rollout is staged with stop conditions and an env-flag
rollback that needs no redeploy.

## Repo-verified facts (checked 2026-05-24 against the tracked code)

Read these before trusting any number below — several were stale in the first draft.

- **The forward-indexer systemd unit has NO `MemoryHigh`/`MemoryMax` directives.**
  `deploy/forward_indexer/systemd/forward-indexer.service` sets only
  `Restart=on-failure`, `RestartSec=10`, `KillSignal=SIGTERM`, `TimeoutStopSec=60`.
  The "MemoryHigh=1200M/MemoryMax=1500M" from commit `392b4d2` is **not in the
  unit file** — that commit only added a doc (`SESSION_PROMPT_FRIDAY_2026-05-22.md`).
  So the indexer's effective memory cap is whatever was applied directly on the box
  (possibly nothing, in which case only the kernel OOM killer applies).
  **→ Verify the real cap on the box first (GATE 0); do not assume 900M or 1200M.**
- **Indexer stop is graceful but fast, NOT "no wait".** On `SIGTERM` the runner
  installs a handler → `stop()` → flushes all venue buffers + the parquet writer →
  exits (`runner.py` `_install_signal_handlers` / `stop`). Bounded by
  `TimeoutStopSec=60`. In practice it exits in a few seconds. The genuinely slow
  graceful stop is the **resolution watcher** (`TimeoutStopSec=900`). So "the slow
  one is the watcher" is right; "the indexer has no graceful wait" is not.
- **Confirmed-real heartbeat fields:** `forward_indexer_heartbeat` already emits
  `memory_mb` and `snapshots_per_second` (`runner.py:252`). Use these as-is.
- **PROVISIONAL identifiers (do NOT exist until the capture-change code is written):**
  the env vars `PM_EDGE_NEAR_RESOLUTION_*`, the heartbeat field
  `near_resolution_markets_active`, and `snapshot_source='near_resolution_hicad'`
  are proposed names. **Reconcile every name in this runbook against the actual
  code once the agent returns it** — if they don't match, the monitoring and the
  data-isolation both silently fail.

---

## GATE 0 — Verify the real environment (do this first, every time)

Capture current healthy numbers AND the actual memory cap, so "fine vs intervene"
is unambiguous and anchored to the real wall.

```bash
ssh pmedge@165.245.235.75 '
echo "=== effective memory cap (authoritative, regardless of where set) ===";
systemctl show forward-indexer -p MemoryHigh -p MemoryMax -p MemoryCurrent;
echo "=== mem ==="; free -m;
echo "=== load ==="; uptime;
echo "=== last heartbeat ===";
sudo journalctl -u forward-indexer --since "2 minutes ago" --no-pager | grep heartbeat | tail -2'
```

Record what you actually see (do not copy the examples):

- **`MemoryHigh` (the wall)** = ________  ← call this **HIGH** below. If it reports
  `infinity`, there is NO cgroup cap — only the kernel OOM killer; treat ~80% of
  total RAM as HIGH and be more conservative.
- `MemoryCurrent` (now) = ________
- `memory_mb` (heartbeat) = ________   (expected baseline this week: ~260–560M)
- `snapshots_per_second` = ________    (expected baseline: ~15–35)
- Load average = ________             (expected: ~1–2)
- Swap used (`free -m`) = ________     (expected: low / draining)

> **All memory thresholds below are written as fractions of HIGH, with example
> absolute numbers assuming HIGH≈1200M. If your verified HIGH differs, re-scale
> the absolute numbers before you start.** Intervene tier: ~0.75×HIGH rising;
> hard wall: HIGH.

---

## GATE 1 — Deploy code with flag OFF (no-op verification)

The code ships disabled by default. This gate proves the deploy itself changed nothing.

```bash
# Laptop: merge/deploy as usual (flag defaults OFF in code)
# VPS:
ssh pmedge@165.245.235.75
cd /opt/pm-edge
git pull origin main
sudo /root/.local/bin/uv pip install --python /opt/pm-edge/.venv/bin/python -e ".[dev]"
sudo systemctl restart forward-indexer    # SIGTERM flush+exit, usually seconds (cap 60s)

# Verify no-op: wait 2 min, check heartbeat
sleep 120
sudo journalctl -u forward-indexer --since "2 minutes ago" --no-pager | grep heartbeat | tail -3
```

**PASS criteria (all must hold):**
- No new near-resolution activity (the provisional `near_resolution_markets_active`
  field, if emitted when disabled, is `0`; or absent entirely).
- `memory_mb` within GATE 0 baseline.
- `snapshots_per_second` within GATE 0 baseline.
- Load average unchanged.

**STOP if:** anything moved from baseline. A behavior change with the flag OFF is a
CODE bug, not the feature. Do not enable. Investigate or roll back the deploy.

---

## GATE 2 — Enable CONSERVATIVE (1/3 of target pressure)

First live exposure at a third of the write pressure. Start small.

```bash
# Set conservative env overrides where the indexer reads its environment:
# the unit uses EnvironmentFile=/opt/pm-edge/.env — add these there (or as
# [Service] Environment= lines if you switch to that pattern). VERIFY the exact
# variable names against the code the agent returns; the names below are PROVISIONAL.
#   PM_EDGE_NEAR_RESOLUTION_CAPTURE_ENABLED=true
#   PM_EDGE_NEAR_RESOLUTION_MAX_MARKETS=10        # NOT 30
#   PM_EDGE_NEAR_RESOLUTION_CADENCE_SECONDS=5     # NOT 2
#   PM_EDGE_NEAR_RESOLUTION_WINDOW_SECONDS=1800

sudo systemctl daemon-reload    # only needed if the unit file itself was edited
sudo systemctl restart forward-indexer
```

**Then WATCH for one full near-resolution window (~30 min).** You need a market
actually within 30 min of close for the feature to do anything — if nothing is
near close, wait until something is (Kalshi sports markets close throughout the
day). Monitor in a loop:

```bash
# Run this every few minutes during the window
sudo journalctl -u forward-indexer --since "3 minutes ago" --no-pager | grep heartbeat | tail -2
free -m
uptime
```

**Watch these fields against thresholds (memory relative to verified HIGH):**

| Field | Healthy | INTERVENE |
|---|---|---|
| `memory_mb` | < ~0.6×HIGH (≈700M @1200M) | climbing past ~0.65×HIGH (≈750M) and not leveling → shed/disable |
| `near_resolution_markets_active` *(provisional)* | ≤ 10 (the cap) | > 10 → cap logic broken, DISABLE NOW |
| `snapshots_per_second` | baseline + ~2 | unbounded growth → DISABLE |
| Load avg | < 3 | climbing toward 5+ → thrash risk, DISABLE |
| Swap used | flat/draining | climbing steadily → thrash canary, DISABLE |

**PASS criteria:** one full window completes with hi-cad snapshots written
(the provisional `snapshot_source='near_resolution_hicad'` — or whatever the code
actually tags them — appearing in the data), cap respected, memory and load within
healthy bounds the whole time.

**STOP/ROLLBACK if** any INTERVENE threshold trips (see ROLLBACK below).

---

## GATE 3 — Step up to TARGET settings

Only after a clean conservative window.

```bash
#   PM_EDGE_NEAR_RESOLUTION_MAX_MARKETS=30
#   PM_EDGE_NEAR_RESOLUTION_CADENCE_SECONDS=2
sudo systemctl daemon-reload    # if unit edited
sudo systemctl restart forward-indexer
```

**WATCH the first full window at full settings**, same fields, tighter memory band:

| Field | Healthy | INTERVENE |
|---|---|---|
| `memory_mb` | < ~0.65×HIGH (≈750M @1200M) | past ~0.7×HIGH (≈800M) rising → shed/disable (HIGH is the wall) |
| `near_resolution_markets_active` *(provisional)* | ≤ 30 | > 30 → DISABLE NOW |
| `snapshots_per_second` | baseline + ~15 | unbounded → DISABLE |
| Load avg | < 3 | toward 5+ → DISABLE |
| Swap | flat/draining | climbing → DISABLE |

**PASS:** clean full-settings window, `memory_mb` comfortably under HIGH, cap holds.
→ Feature is live. The 2-week accumulation clock starts now. Record the date.

---

## ROLLBACK — flag flip, no redeploy

The feature is env-flagged, so rollback is a flag flip + restart (SIGTERM flush+exit,
usually seconds, bounded by `TimeoutStopSec=60` — faster than the watcher's 900s):

```bash
# Disable the feature: set the enable flag back to false in the EnvironmentFile/.env
#   PM_EDGE_NEAR_RESOLUTION_CAPTURE_ENABLED=false
sudo systemctl restart forward-indexer    # daemon-reload first only if the unit was edited
# Confirm back to baseline
sleep 60; sudo journalctl -u forward-indexer --since "1 minute ago" --no-pager | grep heartbeat | tail -2
free -m
```

**Nuclear option (saves the box, loses capture):** if the box is thrashing and
unresponsive and you can't flip the flag fast enough:
```bash
sudo systemctl stop forward-indexer    # halts ALL capture — last resort
```
Then fix the env flag while stopped, and restart. Losing capture beats OOM-killing
a thrashing box.

---

## After a clean GATE 3

1. **Commit the enabled settings to the repo** so a future redeploy doesn't revert
   them — and while you're there, **fix the unit drift**: if the indexer is meant
   to have `MemoryHigh`/`MemoryMax`, add them to the tracked
   `deploy/forward_indexer/systemd/forward-indexer.service` (it currently has none),
   so the repo matches the box.
2. **Pre-register the Exp 2 kill condition** in RESEARCH_LOG.md / EdgeHuntPlan.md
   BEFORE any analysis (do it now, while you can't see results):
   > Exp 2 analysis (~2 weeks out): in the hi-cad near-resolution window, does the
   > price move BEFORE the public event signal, or only with/after it? KILL if the
   > price moves with-or-after the event with no capturable lead, OR if any lead is
   > sub-second / smaller than spread+fees (untradeable). PURSUE only if a
   > consistent, exploitable lead/lag pattern exists above transaction costs.
3. **Set a calendar reminder** for the 2-week analysis date.
4. **Do NOT walk away the first day.** Check the heartbeat a few times over the
   first 24h to confirm memory stays bounded as more markets cycle through windows.

## Don't-forget notes

- Indexer stop flushes buffers on SIGTERM and exits in seconds (cap 60s); the
  watcher is the slow one (`TimeoutStopSec=900`) — don't conflate them.
- The compaction job (`scripts/compact_parquet.py`) already skips today's
  partition, so the extra hi-cad snapshots won't be touched until the day after —
  no interaction risk.
- Confirm hi-cad snapshots are actually tagged distinctly in the data (whatever the
  code names the source). Without a distinct tag the experiment's data can't be
  isolated from normal captures and the whole 2 weeks is wasted.
- Re-anchor every memory threshold to the **verified** HIGH from GATE 0; the
  absolute numbers in the tables assume HIGH≈1200M and are illustrative.
