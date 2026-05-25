# Experiment 2 — Near-Resolution Capture: Deploy & Monitor Runbook
_Created 2026-05-24. Amended 2026-05-24 (reconciliation pass): memory thresholds
re-anchored to the real 1500M wall, unit-deploy `cp` step added, duration/stop rule
+ kill condition pre-registered. Final pass: identifier names CONFIRMED against the
capture-change code; documented the close-filter relaxation (two-axis load) and the
hi-cad auto-shed at `max_memory_mb` (raise to ~1300M for Exp 2)._

_Supervised rollout of a memory-risky capture change on a box with an OOM/thrash
history. Do NOT deploy-and-walk-away. Stay on the box for the first full
near-resolution window at each settings tier._

## Why this runbook exists

The near-resolution capture mode increases write volume and snapshot count with
dedup disabled — on the forward indexer, the subsystem that OOM-killed once and
that thrashed the box to load 15 this week. This is exactly the kind of change
that spikes memory. The rollout is staged with stop conditions and an env-flag
rollback that needs no redeploy.

## Repo-verified facts (checked 2026-05-24 against the tracked code)

Read these before trusting any number below.

- **The forward-indexer unit now declares `MemoryHigh=1500M` / `MemoryMax=1800M`**
  (`deploy/forward_indexer/systemd/forward-indexer.service`, added 2026-05-24 for the
  4GB box; the live box runs these too). This closed an earlier gap where the unit
  had NO caps while commit `392b4d2`'s message *claimed* 1200M/1500M but only touched
  a doc. `MemoryHigh` is the soft wall (kernel reclaims pages above it — gentle
  degradation), `MemoryMax` the hard cgroup cap. **Still verify the live values via
  GATE 0 (`systemctl show`) — the box is authoritative, not this doc.**
- **Indexer stop is graceful but fast, NOT "no wait".** On `SIGTERM` the runner
  installs a handler → `stop()` → flushes all venue buffers + the parquet writer →
  exits (`runner.py` `_install_signal_handlers` / `stop`). Bounded by
  `TimeoutStopSec=60`. In practice it exits in a few seconds. The genuinely slow
  graceful stop is the **resolution watcher** (`TimeoutStopSec=900`). So "the slow
  one is the watcher" is right; "the indexer has no graceful wait" is not.
- **Confirmed-real heartbeat fields:** `forward_indexer_heartbeat` already emits
  `memory_mb` and `snapshots_per_second` (`runner.py:252`). Use these as-is.
- **Identifiers — CONFIRMED against the capture-change code.** The env vars
  `PM_EDGE_NEAR_RESOLUTION_CAPTURE_ENABLED` / `_WINDOW_SECONDS` / `_CADENCE_SECONDS`
  / `_MAX_MARKETS` (`src/core/config.py`), the heartbeat field
  `near_resolution_markets_active` (`runner.py` heartbeat), and the snapshot_source
  tag `near_resolution_hicad` (`runner.py` `NEAR_RESOLUTION_SOURCE`) all match the
  producer code and the consumer `scripts/experiment_02_capture_rate.py`
  (`HICAD_SOURCE`). Verified at the bundle commit.
- **Enabling the feature relaxes the discovery close-filter — it un-drops near-close
  markets.** With the flag ON, `discover_once` sets `min_time_to_close_hours=0`, so
  markets are tracked all the way to close (the default 2h filter would otherwise
  drop them before the hi-cad window opens, and the feature would capture nothing).
  Consequence: enabling adds load on **two axes** — the hi-cad 30-min window AND
  normal-cadence (15s) capture of every near-close market in its final ~2h that was
  previously dropped. Expect a higher normal-capture baseline, not just hi-cad
  volume. (Flag OFF: the filter is unchanged, byte-identical behaviour.)
- **Hi-cad auto-sheds at `max_memory_mb`** (env `PM_EDGE_FORWARD_INDEXER_MAX_MEMORY_MB`,
  code default 1024M) — NOT at the 1500M cgroup wall. This is the app's own ceiling
  and the FIRST line of defense (it sheds hi-cad markets to zero, logged as
  `forward_indexer_near_resolution_shed`), below the operator's manual intervene
  points and well below the kernel reclaim at MemoryHigh=1500M. **Set to 1300M in the
  tracked unit** (`forward-indexer.service` `Environment=PM_EDGE_FORWARD_INDEXER_MAX_MEMORY_MB=1300`)
  — not in `.env` — because it is load-bearing for experiment correctness and must
  survive redeploys (at the 1024M default the shed fires early under the raised
  two-axis baseline and under-captures). 1300M sits just under the 1500M wall and
  matches the GATE 3 intervene guidance. Deploy it the same way as the caps:
  `cp` the unit + `daemon-reload`; verify with `systemctl show -p Environment`.

## Deploying a unit-file change (read once)

`setup_vps.sh` **copies** the unit to `/etc/systemd/system/` — it is not symlinked
to the repo. So a `git pull` alone does NOT update the live unit (learned the hard
way). Any time the `.service` file changes, the deploy is:

```bash
sudo cp /opt/pm-edge/deploy/forward_indexer/systemd/forward-indexer.service \
  /etc/systemd/system/forward-indexer.service
sudo systemctl daemon-reload
sudo systemctl restart forward-indexer
```

Feature flags here are set via `EnvironmentFile=/opt/pm-edge/.env`, which does NOT
need a `cp` — only `daemon-reload` is not even required for `.env` edits, just a
restart. The `cp` + `daemon-reload` dance is specifically for `.service` edits.

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

- **`MemoryHigh` (the wall)** = ________  ← call this **HIGH** below. Expect
  `1572864000` (=1500M). If it reports `infinity`, the cap did not deploy — fix that
  before proceeding (see "Deploying a unit-file change").
- `MemoryCurrent` (now) = ________
- `memory_mb` (heartbeat) = ________   (expected baseline this week: ~260–560M)
- `snapshots_per_second` = ________    (expected baseline: ~15–35)
- Load average = ________             (expected: ~1–2)
- Swap used (`free -m`) = ________     (expected: low / draining)

> **All memory thresholds below are written as fractions of HIGH, with example
> absolute numbers assuming HIGH≈1500M. If your verified HIGH differs, re-scale the
> absolute numbers before you start.** Intervene tier: ~0.75×HIGH (≈1100M) and
> rising; hard wall: HIGH (1500M; the hard cgroup cap MemoryMax=1800M is above it).

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
# If this deploy ALSO changed the .service file (e.g. memory caps), update the unit
# too — git pull does NOT update the live unit:
#   sudo cp deploy/forward_indexer/systemd/forward-indexer.service /etc/systemd/system/
#   sudo systemctl daemon-reload
sudo systemctl restart forward-indexer    # SIGTERM flush+exit, usually seconds (cap 60s)

# Verify no-op: wait 2 min, check heartbeat
sleep 120
sudo journalctl -u forward-indexer --since "2 minutes ago" --no-pager | grep heartbeat | tail -3
```

**PASS criteria (all must hold):**
- No new near-resolution activity: `near_resolution_markets_active=0` in the
  heartbeat (the loop is not even scheduled when the flag is OFF).
- `memory_mb` within GATE 0 baseline.
- `snapshots_per_second` within GATE 0 baseline.
- Load average unchanged.

**STOP if:** anything moved from baseline. A behavior change with the flag OFF is a
CODE bug, not the feature. Do not enable. Investigate or roll back the deploy.

---

## GATE 2 — Enable CONSERVATIVE (1/3 of target pressure)

First live exposure at a third of the write pressure. Start small.

```bash
# Set conservative env overrides in the indexer's EnvironmentFile (/opt/pm-edge/.env).
# Variable names below are CONFIRMED against the capture code (src/core/config.py).
#   PM_EDGE_NEAR_RESOLUTION_CAPTURE_ENABLED=true
#   PM_EDGE_NEAR_RESOLUTION_MAX_MARKETS=10        # NOT 30
#   PM_EDGE_NEAR_RESOLUTION_CADENCE_SECONDS=5     # NOT 2
#   PM_EDGE_NEAR_RESOLUTION_WINDOW_SECONDS=1800
# NOTE: the app memory ceiling (PM_EDGE_FORWARD_INDEXER_MAX_MEMORY_MB=1300) is NOT
# set here — it lives in the tracked unit's Environment= so it survives redeploys.
# Ensure the unit is the current version on the box (cp + daemon-reload) and confirm
# with: systemctl show forward-indexer -p Environment | tr ' ' '\n' | grep MAX_MEMORY

# .env edits need only a restart. If you updated the .service file, also:
#   sudo cp deploy/forward_indexer/systemd/forward-indexer.service /etc/systemd/system/
#   sudo systemctl daemon-reload
sudo systemctl restart forward-indexer
```

> **Expect a higher baseline than hi-cad volume alone.** Enabling the flag also
> un-drops near-close markets (the close-filter relaxation), so normal-cadence
> capture of markets in their final ~2h resumes too. Memory climbing above the
> GATE 0 baseline at GATE 2 is partly this documented two-axis load — not
> necessarily a bug. The code auto-sheds hi-cad at `max_memory_mb` before the
> manual intervene points below; a `near_resolution_markets_active` drop to 0 with
> a `forward_indexer_near_resolution_shed` log is the guard working.

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

**Watch these fields against thresholds (memory relative to verified HIGH=1500M):**

| Field | Healthy | INTERVENE |
|---|---|---|
| `memory_mb` | < ~0.73×HIGH (≈1100M @1500M) | climbing past ~0.8×HIGH (≈1200M) and not leveling → shed/disable |
| `near_resolution_markets_active` | ≤ 10 (the cap) | > 10 → cap logic broken, DISABLE NOW |
| `snapshots_per_second` | baseline + ~2 | unbounded growth → DISABLE |
| Load avg | < 3 | climbing toward 5+ → thrash risk, DISABLE |
| Swap used | flat/draining | climbing steadily → thrash canary, DISABLE |

**PASS criteria:** one full window completes with hi-cad snapshots written
(`snapshot_source='near_resolution_hicad'` appearing in the data), cap respected,
memory and load within healthy bounds the whole time.

**STOP/ROLLBACK if** any INTERVENE threshold trips (see ROLLBACK below).

---

## GATE 3 — Step up to TARGET settings

Only after a clean conservative window.

```bash
#   PM_EDGE_NEAR_RESOLUTION_MAX_MARKETS=30
#   PM_EDGE_NEAR_RESOLUTION_CADENCE_SECONDS=2
# .env edit -> just restart; .service edit -> cp + daemon-reload first (see above).
sudo systemctl restart forward-indexer
```

**WATCH the first full window at full settings**, same fields, tighter memory band:

| Field | Healthy | INTERVENE |
|---|---|---|
| `memory_mb` | < ~0.8×HIGH (≈1200M @1500M) | past ~0.87×HIGH (≈1300M) rising → shed/disable (HIGH=1500M is the wall) |
| `near_resolution_markets_active` | ≤ 30 | > 30 → DISABLE NOW |
| `snapshots_per_second` | baseline + ~15 | unbounded → DISABLE |
| Load avg | < 3 | toward 5+ → DISABLE |
| Swap | flat/draining | climbing → DISABLE |

> Memory bands assume `PM_EDGE_FORWARD_INDEXER_MAX_MEMORY_MB=1300` (set in the
> tracked unit's `Environment=`), so the code's auto-shed (~1300M) and the manual
> `memory_mb` intervene point (~1300M) coincide — the shed fires first, the manual
> row is the backstop if it doesn't hold. Same two-axis baseline caveat as GATE 2
> applies, larger here at full settings.

**PASS:** clean full-settings window, `memory_mb` comfortably under HIGH, cap holds.
→ Feature is live. The accumulation clock starts now — record the date and track it
with the rate check (see **Duration & stop rule**).

---

## ROLLBACK — flag flip, no redeploy

The feature is env-flagged, so rollback is a flag flip + restart (SIGTERM flush+exit,
usually seconds, bounded by `TimeoutStopSec=60` — faster than the watcher's 900s):

```bash
# Disable the feature: set the enable flag back to false in the EnvironmentFile/.env
#   PM_EDGE_NEAR_RESOLUTION_CAPTURE_ENABLED=false
sudo systemctl restart forward-indexer    # .env edit needs only a restart
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

## Duration & stop rule (pre-registered)

Pre-registered BEFORE any data accumulates, so the duration can't quietly stretch.
**"Collect until it works" is forbidden** — that is how a 15%-prior experiment
becomes a permanent cost.

- **Target:** ~150 clean hi-cad-captured **resolved** Kalshi events before the Exp 2
  analysis is trusted. The high end is deliberate: small-n positives in this project
  have consistently been noise (Entries 19–24).
- **48h GATE:** run `scripts/experiment_02_capture_rate.py` 48h after GATE 3 and read
  the days-to-150 projection.
  - On track for **≤3 weeks** → continue.
  - Projection **>4 weeks** → decision point: widen the near-resolution window
    (`PM_EDGE_NEAR_RESOLUTION_WINDOW_SECONDS`), raise the market cap
    (`PM_EDGE_NEAR_RESOLUTION_MAX_MARKETS` — re-watch memory per GATE 3 if you do), or
    stop. A 15% prior is not worth 6 weeks.
- **Week-1 GATE:** re-run the rate check, re-project, decide again.
- **Hard patience stop: 3 weeks maximum**, regardless — unless the week-1 check shows
  150 is clearly reachable just past it.
- **Stop when the target is hit OR the patience limit is reached, whichever comes
  first.**

---

## After a clean GATE 3

1. **Commit the enabled feature settings** so a future redeploy doesn't revert them.
   (The memory caps are already in the tracked unit — `MemoryHigh=1500M`/
   `MemoryMax=1800M` — so no unit drift remains to fix.)
2. **Pre-register the Exp 2 KILL CONDITION** in RESEARCH_LOG.md / EdgeHuntPlan.md
   BEFORE any analysis (do it now, while you can't see results):
   > In the hi-cad window, does price move BEFORE the public event signal, or only
   > with/after it? KILL if price moves with-or-after with no capturable lead, OR if
   > any lead is sub-second / smaller than spread+fees (untradeable). PURSUE only if a
   > consistent, exploitable lead/lag pattern exists above transaction costs.
3. **Track the rate** with `scripts/experiment_02_capture_rate.py` at 48h and week 1,
   per the Duration & stop rule. Set a calendar reminder for the projected target
   date (and the 3-week patience stop).
4. **Do NOT walk away the first day.** Check the heartbeat a few times over the
   first 24h to confirm memory stays bounded as more markets cycle through windows.

## Don't-forget notes

- Indexer stop flushes buffers on SIGTERM and exits in seconds (cap 60s); the
  watcher is the slow one (`TimeoutStopSec=900`) — don't conflate them.
- The compaction job (`scripts/compact_parquet.py`) already skips today's
  partition, so the extra hi-cad snapshots won't be touched until the day after —
  no interaction risk.
- The producer MUST tag hi-cad snapshots `snapshot_source='near_resolution_hicad'`
  exactly — the capture-rate check and the whole 2-week isolation depend on that
  literal tag.
- Re-anchor every memory threshold to the **verified** HIGH from GATE 0; the
  absolute numbers in the tables assume HIGH≈1500M and are illustrative.
