# pm-edge — Edge-Hunt Experiment Plan
_Created 2026-05-24. The disciplined program for determining whether a tradeable edge exists._

## Purpose

This plan exists to answer one question without fooling ourselves: **is there a
tradeable, exploitable edge in prediction markets capturable with the pm-edge
infrastructure?** It ranks candidate experiments by estimated probability of
success, defines each one's test and kill condition in advance, and is worked
top-down. Each experiment either produces a pre-registered signal or is marked
dead. No experiment gets "one more look" past its kill condition.

## What is already DEAD (do not re-run)

These were tested and falsified. Re-running them is sunk-cost behavior.

| Hypothesis | Result | Why it died |
|---|---|---|
| Calibration gap (markets misprice YES) | NULL | Lag artifact; well-calibrated once controlled (Brier 0.159) |
| Depth imbalance predicts outcome | NULL | p=0.47–0.50, AIC worse; static book = price proxy |
| Price velocity predicts outcome | NULL | p=0.97 at n=86; no movement to have velocity |
| Price volatility predicts outcome | NULL | 95% of Kalshi markets have ~0 volatility pre-resolution; fit degenerate |

**Root cause unifying all four (Entry 23 finding):**
- **Kalshi**: prices freeze 2+ hours pre-resolution (96% of markets show ≤1
  distinct mid in the [-120,-30]min window despite ~353 snapshots). No trajectory.
- **Polymarket**: capture-to-resolution lag is median ~16h (max 9.5 days) because
  markets enter the resolved set via disappeared-detection long after going quiet.
  No near-resolution book.

**Conclusion of Phase A (microstructure-at-resolution):** static and trajectory
features of the captured book do NOT beat the mid-price on either venue. That door
is closed. The experiments below are the doors that remain open.

---

## RANKED EXPERIMENTS (work top-down)

Ranking is by estimated P(yields tradeable edge), informed by what we now know.
Probabilities are honest priors, not promises — most are low, because efficient
markets are the default.

### Experiment 1 — Market SELECTION on thin/illiquid markets
**Estimated P(success): ~25% — highest, because we tested the worst case first**

**Thesis:** We accidentally tested the most efficient markets that exist (Kalshi
MLB sports lines, heavily arbitraged). Retail mispricing persists in *illiquid,
low-attention* markets — niche Polymarket politics/culture, long-tail Kalshi
events — not liquid sports. Edge may be in *which markets to be in at all*, not
microstructure.

**Test:** Segment the full resolved set by liquidity/volume tier. Compute Brier
and calibration gap per tier. Hypothesis: low-volume markets show systematically
worse calibration (larger, consistent gaps) than high-volume markets. If the
bottom liquidity quartile shows a |gap| > 0.05 that's consistent in sign within a
category, that's a candidate edge: bet the calibrated direction on illiquid markets.

**Data needed:** already have it. Resolved set + metadata volume/liquidity fields.

**Kill condition:** if calibration gap does not worsen monotonically with
illiquidity, OR the low-liquidity mispricing has inconsistent sign (can't predict
direction), → DEAD. Illiquidity alone isn't edge.

**Why ranked #1:** cheapest (existing data), and directly attacks the strongest
confound in all prior nulls (we only looked at efficient markets).

---

### Experiment 2 — Near-resolution repricing window (the unfreezing)
**Estimated P(success): ~15%**

**Thesis:** Kalshi prices snap from frozen to resolved with no captured
intermediate states. ALL price discovery happens in a window we don't capture. If
edge exists in these markets, it lives in the final minutes when the outcome
becomes clear and the price moves — and we have zero data on it.

**Test (requires a capture change first):** Modify forward indexer to high-cadence
capture (every 1–2s, dedup disabled) for markets within ~30min of expected close.
Accumulate 2 weeks. Then ask: does the price move *before* the public signal (the
game event), *with* it, or *after* it? Only "before" or a capturable "after"-lag
is tradeable.

**Data needed:** NEW capture mode — does not exist yet. ~1-2 day build + 2 week wait.

**Kill condition:** if the price moves with-or-instantly-after the event with no
capturable lead/lag pattern → DEAD, and this is a genuine efficiency proof for
Kalshi sports. If the lag exists but is sub-second / spread-eaten → DEAD (not
manually tradeable).

**Why ranked #2 not #1:** requires building + waiting before it can even be tested,
and sports-market final-minutes are exactly where HFT/sharp money concentrates, so
prior is low. But it's the one place the data explicitly points.

---

### Experiment 3 — Time-horizon calibration (mispricing far from resolution)
**Estimated P(success): ~12%**

**Thesis:** Markets are well-calibrated AT resolution (proven) but may be poorly
calibrated 6–24h before. Edge = enter early when mispriced, exit/hold to resolution.

**Test:** For resolved markets with long pre-resolution histories, compute implied
prob at T-1h, T-6h, T-24h (not just final). Calibration at each horizon. Hypothesis:
gap widens at longer horizons. If T-24h shows a consistent exploitable gap that
converges by resolution, that's a hold-to-resolution edge.

**Data needed:** have it for Polymarket (which has price movement); Kalshi frozen
prices make this Polymarket-only in practice.

**Kill condition:** if calibration is flat across horizons (well-calibrated at
T-24h too) → DEAD. If gap exists but is within transaction costs/spread → DEAD.

**Why ranked here:** plausible mechanism (information arrives over time), but
Polymarket's loose capture/resolution pairing (the 16h-lag problem) makes the data
messy, and the "hold to resolution" strategy ties up capital with settlement risk.

---

### Experiment 4 — Cross-market consistency (correlated-market arbitrage)
**Estimated P(success): ~10%**

**Thesis:** Related markets (a team's moneyline vs spread vs total; linked
political markets) should price consistently. Inconsistencies = arbitrage or at
least a directional signal.

**Test:** Identify market families (shared event/underlying). Check whether implied
probabilities are mutually consistent (e.g., conditional probabilities that should
sum/bound each other). Flag violations; check if betting the "correct" side of an
inconsistency profits at resolution.

**Data needed:** have it, but requires building market-family grouping logic.

**Kill condition:** if inconsistencies are absent, or present but smaller than
spread+fees → DEAD.

**Why ranked here:** real mechanism and venue-internal (less HFT-contested than
sports finals), but cross-market arb in liquid prediction markets is well-trodden;
prior is low that retail-capturable inefficiency survives.

---

### Experiment 5 — Cross-VENUE divergence (Kalshi vs Polymarket same event)
**Estimated P(success): ~8%**

**Thesis:** When the same real-world event trades on both venues, prices may
diverge (different participant pools, no cross-venue arb infrastructure for retail).

**Test:** Match equivalent markets across venues. Measure price divergence. Check
if the divergence predicts which venue was "right" at resolution, or if a
divergence-convergence trade profits.

**Data needed:** have both venues; requires building a cross-venue event-matching
layer (hard — different ID schemes, different market definitions).

**Kill condition:** if matched events price within spread of each other, or
divergence doesn't predict resolution → DEAD.

**Why ranked low:** event-matching across venues is genuinely hard (the two venues
rarely list *identical* contracts), so the sample of truly-comparable pairs may be
tiny. High effort, uncertain sample.

---

## PREREQUISITE FIXES (blockers, not experiments)

These don't find edge but unblock experiments / backtesting:

- **P0a — Simulator resting-order ValueError** (`fill_logic.py:42,61`): blocks any
  maker-side backtest. Needed before any experiment graduates from "calibration
  gap exists" to "tradeable after costs."
- **P0b — Simulator top-of-book-only fills**: the depth-dependence finding (27% of
  large trades walk the book) proves this mismodels large orders. Needed before
  trusting any backtest P&L with non-trivial size.
- **Polymarket `final_*` field population**: convenience — analysis currently must
  derive final book by joining to snapshots (works, just tedious).

---

## WORKING PROTOCOL (the discipline)

1. Work strictly top-down. Don't skip to a lower experiment because it's more
   interesting.
2. For each experiment: state the pre-registered prediction and kill condition
   BEFORE running. Write both into RESEARCH_LOG.md.
3. Apply the lag/confound lens that killed the velocity result. A positive at
   small n is presumed overfit until it survives a larger clean sample.
4. A kill is a SUCCESS of the process — it removes a door and saves money.
5. If all five experiments hit their kill conditions: that is the answer. Tradeable
   edge is not capturable with this infrastructure on these venues. Document it,
   shut down the VPS, keep the data and code. A complete negative result is a
   finished investigation, not a failure.
6. Hard budget/time stop: revisit the whole program after Experiment 1 + 2
   resolve. If both die, seriously weigh stopping before sinking weeks into 3–5.

## Estimated aggregate

If P(success) values are roughly independent, P(at least one yields tradeable
edge) ≈ 1 − (0.75)(0.85)(0.88)(0.90)(0.92) ≈ **~52%**. Honest read: roughly a
coin-flip that *something* here is real, concentrated almost entirely in
Experiments 1 and 2. That is worth pursuing — but with the kill conditions firmly
in place, because the base rate of "retail finds durable edge in prediction
markets" is low and the failure mode is expensive.
