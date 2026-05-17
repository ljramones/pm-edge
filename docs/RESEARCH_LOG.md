# pm-edge Research Log

This log captures hypotheses, architectural patterns, decisions, and open questions developed during pm-edge research that do not belong in code documentation or in `DATA_QUALITY_LESSONS.md`. The file is append-only: entries are dated and never edited after the fact except to mark them resolved, refuted, or superseded. The purpose is to give future-self and future collaborators a faithful record of the reasoning path, including dead ends and abandoned ideas, not just the final design.

## 2026-05-14 - Out-of-band signal thesis [HYPOTHESIS]

**Core thesis:** Edge in prediction markets is more likely to come from out-of-band signals, meaning signals that exist outside the order book itself, than from cleverer analysis of in-band price and volume data. Price-derived features are accessible to every other participant, so any edge derived purely from them faces immediate competition. Out-of-band signals require domain knowledge or specific information access that competing participants do not necessarily have.

Reference examples documenting the pattern:

- The loadmaster pattern: a former USAF loadmaster predicted the US would attack Iran by observing the types of aircraft and resources being staged, because the deployment composition matched the operational requirements for that specific operation. The signal, aircraft positioning, was upstream of the event and public but illegible to participants without domain knowledge.
- The Citrini "Atoms Over Bits" thesis and Sprott Asset Management's broader AI-infrastructure framework: the thesis identifies upstream materials demand that the AI infrastructure buildout mathematically requires, including uranium for nuclear baseload, copper for electrification, rare earths, and titanium. Edge comes from reading the operational requirements of a trend before the materials prices fully reflect them.
- Personal precedent: the 20-day cycle finding in prior ETF prediction work emerged from multi-timescale analysis combined with willingness to test for structure that was not in the dominant time horizon.

**Implication:** The right next architectural step after the forward indexer accumulates data is not a more sophisticated price-only model. It is an external-signal ingestion layer that captures upstream observables, time-aligned with the captured book state.

## 2026-05-14 - Causal map approach to market archetypes [DECISION]

**Decision:** Before scaling feature engineering or model training, hand-build causal maps for the top market archetypes. The causal map for each archetype documents the resolution mechanism, causal precursors, observable signals for each precursor, expected lag from signal to resolution, and counter-signals that falsify the thesis.

**Rationale:** Writing the causal map before looking at data forces the structural reasoning that distinguishes signal-hunting from feature-hunting. Without the map, the failure mode is ingesting a generic news pipeline and hoping the model figures out what matters. With the map, the question becomes: which specific signals does this market's causal chain require, and where are they available?

Estimated archetype set, to be refined as the universe is examined:

- Political/electoral resolution
- Macroeconomic / Fed decision
- Geopolitical conflict
- Sports outcomes
- Crypto price thresholds
- Regulatory decisions: SEC, CFTC, FDA
- Judicial outcomes
- Weather and disaster
- Corporate events: M&A, earnings, leadership changes
- Celebrity / cultural

**Pending artifact:** `docs/MARKET_ARCHETYPES.md`. Initialize it after the forward indexer has captured enough resolved markets that examples in each archetype can be examined empirically.

**Methodology note:** When a market resolves in a surprising way, where the market price diverged from the causal-map prediction in either direction, the resolution becomes an explicit map-improvement event. Each surprise either improves the map, expands its scope, or indicates a category the existing maps do not cover.

## 2026-05-14 - DynamisAI design patterns transfer to thesis evaluation [ARCHITECTURAL PATTERN]

**Observation:** The reasoning patterns developed in DynamisAI for NPC belief modeling map structurally to prediction-market thesis evaluation. The mapping is not metaphorical. The same constraints, many entities of varying importance, evidence-driven belief updates, propagation delay, source credibility variance, and limited compute budget, produce the same solutions.

Pattern mapping:

- **Belief states with confidence** in DynamisAI -> **market thesis with confidence** in pm-edge
- **Perception inputs: vision, audio, blackboard messages** -> **evidence sources: filings, on-chain, news, expert accounts**
- **Belief propagation delay through squad blackboards** -> **upstream signal propagation lag from precursor to observable market state**
- **Drama management for narrative pacing** -> **regime detection for market state transitions**
- **Reputation and rumor systems** -> **source credibility tracking with per-archetype track records**
- **GOAP planner choosing next action toward a goal state given current beliefs** -> **research planner choosing next signal source to consult given current thesis uncertainty**
- **LOD tiers: full reasoning for nearby agents, simplified for distant** -> **LOD tiers: full thesis for active markets, monitoring for active-archetype markets, order-book-only for background**

**Decision implication:** When building pm-edge's reasoning layer, borrow DynamisAI's design patterns rather than reaching for off-the-shelf LLM orchestration. Model thesis evaluation as belief plus evidence accumulation with explicit uncertainty, not as score-and-sum classification. Use the LOD tier concept explicitly to make 540+ tracked markets tractable. Use blackboard-style shared state for cross-market signals that affect multiple theses.

**Critical scope discipline:** Do not port DynamisAI code into pm-edge. They are two separate projects and two separate codebases. The transfer is architectural pattern recognition, not code reuse. Tangling the two compromises both.

Known disanalogies that matter:

- Game NPCs operate over minutes-to-hours; prediction markets resolve over days-to-months. Belief decay and lag handling need tuning for the longer horizon.
- DynamisAI operates in a closed simulation with ground truth. Markets are real-world with adversaries; thesis only matters when it differs from and is better than the consensus already in the price.
- Blackboard pattern transfers, but propagation model differs. In games, squad members share knowledge after delay. In markets, signals propagate through the market itself, with price action revealing other participants' theses, and through external information channels.

**Strategic implication:** The prediction-market AI agent landscape is dominated by LangChain-flavored pipelines that look architecturally similar to each other. A system built on game-AI reasoning patterns is structurally different. Whether different is better is empirical, but structural difference is one of the few ways to search for non-consensus signal in a competitive space.

## 2026-05-14 - LOD tiering for tracked market evaluation [ARCHITECTURAL PATTERN]

**Constraint:** The forward indexer tracks about 540 markets in the current operating target. Running full thesis evaluation, including causal map traversal, signal queries, and LLM-based reasoning, on every tracked market every cycle is intractable. Most markets, most of the time, are not in a state where new signal meaningfully changes the resolution probability estimate.

Tier design:

- **Full thesis tier**: target about 5-20 markets. Edge thesis is active, signals are moving, or resolution is approaching. Full causal map evaluation, all signal sources queried, structured thesis output, per-cycle update.
- **Active monitoring tier**: target about 50-150 markets. Active archetype with recent activity. Cheap signal checks, threshold-based escalation to full thesis if signals cross trigger conditions.
- **Background tier**: everything else. Order book monitoring only, with escalation to active monitoring if price movement exceeds expected volatility for the archetype.

**Transitions:** Promotion and demotion between tiers is its own workflow. Triggers include signal-source activity bursts, time-to-resolution thresholds, price volatility crossing archetype-specific bands, and thesis-confidence stabilization. A confident thesis with no new signals can be demoted. An uncertain thesis with active signals gets promoted.

**Open question:** Where should tier-transition logic live? A separate orchestrator is the current leaning, but the implementation decision waits until two tiers exist.

## 2026-05-14 - Multi-timescale analysis is required from day one [DECISION]

**Decision:** When the forward-indexer data is examined, aggregate to multiple timescales, including 1m, 5m, 1h, 6h, 1d, and 7d, rather than only the 15-second native cadence. Test for structure at each timescale independently.

**Precedent:** Prior ETF prediction work found the strongest result at a 20-day cycle. That structure would have been invisible to analysis at the dominant short timescale. The same risk exists here: meaningful structure can exist at timescales other than the 15-second microstructure the indexer captures, and only deliberate multi-timescale examination finds it.

**Implication for analysis:** When the first real analysis session begins, estimated two to three weeks after the forward indexer starts producing clean data, the first work is not feature engineering or model training. It is producing aggregations at multiple timescales and looking for structure at each, including autocorrelation, cyclical patterns, regime shifts, and cross-market correlation patterns.

## 2026-05-14 - External signal sources to investigate [HYPOTHESIS]

This initial list of candidate signal sources is organized by archetype. These are starting points for causal-map work, not commitments. The signal sources for each archetype get tested for predictive value once causal maps are written.

**Political/electoral:**

- FEC filings: campaign contributions, spending patterns
- Lobbyist registrations
- Court docket filings for case-specific markets
- State-level election filings and primary ballot deadlines
- Specific Substack and X accounts with measured track records in political analysis

**Macroeconomic / Fed:**

- Regional Fed president speech schedules
- Dot-plot dispersion from most recent SEP
- Fed Funds futures positioning
- Primary dealer survey results
- High-frequency private data: trucking volume, employment listings, credit card aggregates

**Crypto thresholds:**

- On-chain whale wallet activity: large USDC movements, exchange inflow/outflow
- Funding rate divergence between perp markets and spot
- Stablecoin minting/burning at relevant scale
- Concentrated trading-Discord and X-account activity for the specific assets

**Regulatory: SEC, CFTC, FDA:**

- Comment period activity
- Specific regulator speech itineraries
- PACER filings for related cases
- Industry trade association statements

**Sports:**

- Lineup announcements
- Injury reports from specific beat reporters with measured track records
- Weather for outdoor events
- Late-breaking news from team-specific sources

**General principle:** Most of this data is free or cheap. The cost is not in the data; it is in the connector layer and in the causal-map work that decides which signals are worth ingesting for which archetypes.

## 2026-05-14 - Sequence and methodology principles [DECISION]

The sequence discipline:

1. Causal maps first.
2. Manual archetype evaluator implementation second.
3. Orchestration choice third.

Building orchestration before proven causal maps is putting scaffolding up before deciding what house to build. This is the failure mode of many public AI prediction-market projects on GitHub: scaffolded systems that never reach the point of testing real edge.

**Explain before predict:** Before building a system that predicts market resolutions, manually investigate about 50 resolved markets that surprised the analyst, where the market price diverged from a reasonable prior in either direction. For each, identify what information existed before resolution that would have explained the outcome. This work reveals where the actual signal lives for this universe, not for prediction markets in general.

**Decision quality over implementation speed:** At the velocity AI-assisted implementation enables, the binding constraint is no longer how fast code can be written. It is the quality of the decisions about what code to write. Tasks stay small and focused, with pre-registered kill criteria. Decision points are surfaced explicitly rather than absorbed silently.

## 2026-05-14 - Honest probability assessment [DECISION]

The realistic outcome distribution at this point:

- **Outcome (a) - small persistent edge in a narrow niche, modest absolute dollars:** Plausible. This is the most realistic positive outcome. It requires the out-of-band signal direction, disciplined causal-map work, and several months of accumulated data.
- **Outcome (b) - no edge found, system is engineering portfolio piece:** Plausible. This is at least as likely as outcome (a) on priors. The fixed forward indexer makes this conclusion trustworthy rather than artifact-driven, which is itself valuable.
- **Outcome (c) - scalable edge:** Rare. This requires an out-of-band signal that is genuinely unique, the project's version of the loadmaster signal. Prediction markets have capacity constraints because they are thin.

The strategic direction documented in this log raises the probability of outcome (a) and lowers the probability of outcome (b) relative to a pure price-only approach. It does not guarantee any specific outcome. The system is being built to discover the truth honestly, not to force a positive result.

## Entry 9 — OpenEvolve tool assessment [TOOL ASSESSMENT, 2026-05-14]

OpenEvolve is an open-source implementation of DeepMind's AlphaEvolve. It is Apache-2.0 licensed. Repository: github.com/algorithmicsuperintelligence/openevolve. The project is under active development, with 6.3k GitHub stars, 52 releases through March 2026, and regular maintenance.

Mechanism: evolutionary algorithm where LLMs serve as the mutation operator. Initial program plus evaluator plus iteration budget produces a MAP-Elites quality-diversity population of evolved variants. Island-based architecture prevents premature convergence. The artifacts side-channel feeds execution errors back into subsequent generations as additional context for the LLM. OpenEvolve works with any OpenAI-compatible API, including local Ollama and vLLM endpoints.

**Verified achievements:**

- 2.8x speedup on Apple Silicon Metal attention kernels in the MLX optimization example.
- Matches published state-of-the-art for the n=26 circle packing problem.
- Measurable accuracy gains on prompt evolution: +23% on the HotpotQA benchmark.
- Adaptive sorting algorithms in Rust.
- Symbolic regression for automated equation discovery.

**Applicable to current and planned work:**

1. **Dynamis engine performance optimization.** Hot-function optimization with clear benchmarks. The MLX Metal kernel example is directly analogous to the Vulkan/MoltenVK and Metal optimization work in DLE. The MeshForge OBJ parser bottleneck is the obvious first candidate when this tool is picked up: already profiled, clear hot path, existing benchmark harness adaptable into an OpenEvolve evaluator.
2. **LLM prompt optimization for the multi-agent workflow.** The architect/coding-agent loops in the existing manual orchestration depend on carefully crafted prompts. OpenEvolve's prompt-evolution support has measured improvements on benchmarks. It is worth attempting when a prompt feels almost-right-but-not-quite and the evaluator function for prompt quality is well-defined.
3. **Specific algorithmic challenges with unambiguous fitness.** Pathfinding in TRIPS, procedural generation in the worldbuilding tools, mesh optimization: anywhere the fitness function is clear and the algorithm space is unfamiliar.

**Not applicable to pm-edge strategy evolution:**

- **Overfitting is catastrophic for trading strategies.** Evolutionary search inherently optimizes for the evaluation metric. With historical market data, sufficient search finds strategies that crush in-sample data and resolve to noise out-of-sample. MAP-Elites quality-diversity reduces but does not eliminate this. The pre-Phase-1 dataset failure modes documented in `DATA_QUALITY_LESSONS.md` are the same failure modes evolutionary search would amplify.
- **The hard question in pm-edge is not "what code computes the answer" but "what should the answer even be."** Evolutionary code generation is powerful when fitness is unambiguous: faster runtime, smaller packing. It is dangerous when fitness is ambiguous and contestable, which is the entire situation in trading.
- **The pm-edge methodology is the opposite approach.** Causal maps first, out-of-band signals, multi-timescale analysis, hand-built archetype evaluators. Evolutionary search would be a sophisticated way to fool oneself into believing in artifacts of the search rather than real signals.

**Cost and integration notes:**

- LLM API costs scale with iterations. A realistic optimization run costs about $20-100 in API calls for a few hundred iterations on a hot function. Local Ollama models are cheaper but slower.
- The evaluator is the actual work. The framework handles orchestration; the user writes the fitness function. For Dynamis kernels this means accurate benchmarking harnesses with low variance.
- Local-model compatibility aligns with the existing work-AI policy preference for local inference where practical.
- No corporate dependency issues: Apache-2.0.

**Decision: bookmarked, not adopted.**

OpenEvolve is the right tool for a specific class of problem: well-defined fitness, hot-function optimization, prompt evolution. It is the wrong tool for another class: strategy discovery and ambiguous-fitness problems. The right shape of engagement is "I have a specific optimization problem with a clear evaluator; try OpenEvolve on it" rather than "preemptively integrate evolutionary code generation into the toolchain."

First serious application is queued: when the MeshForge OBJ parser bottleneck is revisited, OpenEvolve gets a real trial. Until then, this is reference material.

**Open question:** Whether OpenEvolve's prompt-evolution mode fits the system messages that eventually drive pm-edge's archetype evaluators. The reasoning is recursive: archetype evaluators use prompts; those prompts can be evolved; but the fitness function would be backtest performance on resolved markets, which carries the same overfitting risk as evolving the strategy code directly. Resolution requires more thought once archetype evaluators exist and produce measurable outputs. Flagged for revisit, not pursued now.

## Entry 10 — 41-hour forward data quality assessment [TOOL ASSESSMENT, 2026-05-16]

Codex inspected the local forward-index parquet archive at latest snapshot timestamp `2026-05-16 13:01:21 -04`, after about 41 hours of capture.

**Verdict:** The captured data is good enough for operational monitoring and first-pass market exploration. It is not yet enough for strategy validation.

**Strong points:**

- `3,961,853` order-book snapshots captured across Polymarket and Kalshi.
- Polymarket has `2,168,075` snapshots in the latest 24-hour window across `584` markets.
- Polymarket source mix is `99.84%` WebSocket and `0.16%` REST in the latest 24-hour window.
- No crossed books, invalid prices, or non-positive spreads were found for either venue in the latest 24-hour window.
- Polymarket spreads are tight in aggregate: median spread `0.002`, p90 spread `0.020`.
- Kalshi book parsing is working: `101,331` snapshots in the latest 24-hour window across `136` markets, median spread `0.01`, p90 spread `0.04`.

**Weak points:**

- Trade capture is Polymarket-only so far. Kalshi trade capture remains absent/deferred.
- Polymarket `trade_id_venue` is empty for all `53,166` captured trade rows. Aggregate trade-flow analysis remains possible, but trade-level deduplication and trade-to-book reconstruction are not reliable until this is fixed.
- Top-of-book completeness is imperfect. In the latest 24-hour window, Polymarket has both top bid and top ask in `79.88%` of snapshots; Kalshi has both in `88.29%`.
- Polymarket empty bid levels are high at `19.82%`; Kalshi empty asks are `7.75%`.
- Latest 24-hour gap check found `6` low 5-minute buckets out of `288` for Polymarket and `56` low 5-minute buckets out of `261` for Kalshi.

**Analysis-ready universe under the first-pass screen:**

Criteria: at least 100 snapshots, observed top-book movement, mean spread no greater than `0.10`, and mostly complete top book.

- Polymarket: `231` markets ready, `316` rejected for no top-book movement, `30` rejected for incomplete top book, `4` rejected for low snapshots, `3` rejected for wide or missing spread.
- Kalshi: `52` markets ready, `71` rejected for no top-book movement, `11` rejected for incomplete top book, `2` rejected for wide or missing spread.

**Action items:**

- Fix empty Polymarket `trade_id_venue` extraction in `src/data/forward_indexer/polymarket.py`.
- Defer Kalshi gap closure to the signed WebSocket-auth phase.
- Defer top-of-book completeness investigation until after trade-ID repair unless the gap worsens.

**Unlocked analysis work:**

- Spread and depth distribution studies by venue and market category.
- Activity classification using the actual analysis-ready universe rather than raw tracked-market counts.
- Identification of anchor markets with the most top-of-book movement for manual "explain this market" investigations.
- Execution simulator input-contract design against real captured book-state schema.

**Still off-limits:**

- PnL backtests against this forward archive.
- Predictive model training on this archive.
- Category-level claims about strategy effectiveness.

This assessment marks the project as materially past the pre-Phase-1 data-quality failure mode. The data is now honest enough to reveal its own limitations, which is different from the legacy signals dataset where the limitations were hidden inside derived features and fallback paths.

## Entry 11 — Execution simulator v0 [INFRASTRUCTURE, 2026-05-16]

**Context**

Built v0 execution simulator per `docs/EXECUTION_SIMULATOR_DESIGN.md`. Goal: reproduce what would have happened to a hypothetical order placed against historical prediction-market book state, as the foundation for future strategy validation work.

**Module structure**

New top-level module at `src/execution_simulator/` containing config, types, book lookup, fill logic, assumption validation, and the public `simulate_order()` / `simulate_strategy()` entry points. It is a sibling to `src/data/`: a consumer of the data archive, not part of the data pipeline.

**v0 scope and deferrals**

v0 implements marketable order fills against the top of the opposing side with conservative defaults: full-spread slippage, `max_book_age_seconds=60`, taker fees at venue maximum, and no resting-order fills under the worst-case queue assumption.

Out of scope for v0 and deferred to v1:

- Depth walking.
- Queue position modeling.
- Fee calibration.
- Partial-fill resting logic.
- Latency simulation.
- Multi-leg orders.

**Conservative-by-default principle**

Every modeling choice that has a more-optimistic and more-pessimistic interpretation defaults to the pessimistic. This is documented in `EXECUTION_SIMULATOR_DESIGN.md` with explicit rationale. The simulator is designed to systematically underestimate, not overestimate, real-trader achievable performance.

**Assumption validation suite**

Five empirical checks run against the local archive, each tied to a specific simulator assumption with a documented threshold:

- `top_of_book_completeness`: at least `70%`.
- `trade_within_spread_rate`: at least `80%`.
- `book_staleness_rate`: no more than `10%`.
- `bid_ask_cross_rate`: no more than `0.1%`.
- `depth_dependency_rate`: quantified.

The suite runs as part of `simulate_strategy()` output so users always see assumption health alongside simulation results.

**Testing**

17 new tests cover types, book lookup, fill logic, end-to-end simulation, and assumption validation. Full test suite at implementation time: `150 passed`.

**End-to-end verification**

Manual smoke test against the real archive at `/Users/larrymitchell/pm-edge-data/forward_index`: 10 synthesized Polymarket orders produced 10 valid `FillOutcome` objects. The pipeline works end-to-end.

**Initial assumption suite result**

`trade_within_spread_rate` reported `0.7026`, failing against the `0.80` threshold and prompting Entry 12 investigation.

**What this unlocks**

Paper strategy testing against simulated fills, with documented conservative bias and assumption-health reporting.

**What it does not unlock**

Production fill expectations or PnL claims. v1 gaps, especially depth walking, are real and quantified in Entry 13.

## Entry 12 — Validator full-archive scan fix [INFRASTRUCTURE, 2026-05-16]

**Context**

Entry 11's initial assumption suite reported `trade_within_spread_rate=0.7026`, below the `0.80` threshold. Investigation determined this was a sampling issue in the validator, not a simulator modeling issue.

**Investigation**

Decomposition by classification and snapshot lag revealed:

- Out-of-spread trades (`above_top_ask`, `below_top_bid`): average lag `4,500-5,100s`.
- Within-spread trades: average lag `578s`.
- Filtering to fresh snapshots, no more than `60s` lag to match the simulator default: `85.4%` within-spread rate, PASS.

The validator was scanning only the 128 most-recently-modified parquet files, a deliberate but undocumented performance optimization by the implementing agent. This produced a sample of about `1,650` trades versus about `52,000` trades available in the full archive. Sample size was insufficient for stable rate estimation, and the file-mtime sort introduced selection bias between `trade_events` and `order_book_snapshots` views.

**Fix**

Replaced the file-sampling logic in `_create_table_or_empty()` with a recursive parquet glob that scans the entire archive. Removed `_latest_partition_paths()` and `_parquet_list_sql()` entirely.

**Verification after fix**

Real archive run with full scan:

- Runtime: `16.31s`, acceptable for an infrequently run check.
- `trade_within_spread_rate`: `0.8411`, PASS.
- `top_of_book_completeness`: `0.8094`, PASS.
- `book_staleness_rate`: `0.0000`, PASS.
- `bid_ask_cross_rate`: `0.0000`, PASS.
- `depth_dependency_rate`: `0.1032`, quantified.

**Methodological note**

The investigation followed the principle of empirical decomposition before changing the simulator. The simulator's conservative defaults turned out to be appropriate; the validator was reporting a misleadingly pessimistic number due to a sampling bug. This is the assumption-validation discipline working correctly: investigate before accepting or dismissing alarms.

**What this taught**

When designing future agent prompts for measurement work, specify data scope explicitly. Leaving "scan the archive" open to interpretation led to a plausibly defensible-looking sampling choice that produced statistically wrong output. Future prompts should say "scan the full archive, no sampling" or "sample with documented methodology" rather than leaving scope implicit.

## Entry 13 — Depth-dependent trade investigation [ANALYSIS, 2026-05-16]

**Context**

Entry 12's assumption suite reported `depth_dependency_rate=0.1032`: about 10% of trades require book depth beyond level 1, which v0 simulator does not model. Goal of this investigation: identify which markets, categories, and order sizes drive depth dependence, so v1 priorities are empirically grounded.

**Investigation scope**

Implemented as Section 6 of `notebooks/2026-05-22-first-look.ipynb`. Four queries: market-level depth-dependence rates, distribution histogram, trade-size bucket analysis, and category aggregation. Kalshi is not analyzed because Kalshi trade capture is deferred to Phase 1.5.

**Headline finding**

`63,293` fresh Polymarket trades analyzed, each within `60s` of a snapshot. `6,340` are depth-dependent, confirming the `10.02%` overall rate.

**Distribution shape: concentrated, not long-tail**

The `234` active markets do not contribute uniformly. Top 5 markets show depth rates of `50-60%`; markets 6-12 show `30-50%`; remaining about 220 markets average below `30%`. This concentration means depth walking is most critical for a specific subset of markets rather than across the entire universe.

**Mechanism distinguishes thin-book from variance-driven**

The top depth-dependent markets fall into two categories:

1. **Thin-book markets:** `avg_trade_size` routinely exceeds `avg_level_1_size`. Example: a market with `avg_trade_size=276` and `avg_level_1_size=170`. Trades structurally consume depth.
2. **Variance-driven markets:** `avg_trade_size` is below `avg_level_1_size`, but specific large trades still need depth. Most trades fill at top; outliers do not.

These distinctions matter for v1 priorities: thin-book markets need depth walking always; variance-driven markets need it only for outlier orders.

**Trade-size threshold**

Size-bucket analysis over `63,293` Polymarket trades:

- Less than `10` contracts: `1.14%` depth-dependent.
- `10-100`: `7.66%`.
- `100-1000`: `19.27%`.
- `1000-10000`: `26.34%`.
- More than `10000`: `25.11%`.

The relationship is monotonic and plateaus around `25%` for large trades. The plateau suggests depth walking deeper than level 2-3 is uncommon, which constrains v1 implementation scope.

**Categorization limitation**

Section 6.4 attempted to group depth-dependent trades by market category. Polymarket markets all classified as `polymarket_unknown` because the implementation parsed category prefixes from `market_id` strings, which works for Kalshi tickers like `KXBTCD` and `KXMLBHR`, but not for Polymarket hex hash IDs without embedded category info. Real categorization for Polymarket requires joining with `market_metadata_snapshots` and extracting event/category fields. Documented as follow-up work.

**Implication for current trading scope**

With `PM_EDGE_MAX_ORDER_NOTIONAL_USD=100`, typical order sizes are `150-300` contracts, landing in the `100-1000` bucket where depth walking matters `19%` of the time. However, the concentration analysis suggests a market filter could substantially close this gap without v1 depth walking: excluding markets where `avg_trade_size > avg_level_1_size * 0.5` would remove most thin-book markets while preserving the about 220 deeper-book markets where v0 simulator is reliable.

**v1 priorities updated**

1. **Market-filter logic first**: about 1 day of work. Filter universe at strategy boundary based on book-depth characteristics. Allows v0 simulator to remain reliable for the filtered universe.
2. **Polymarket category metadata join**: about half a day. Enables real category-level analysis. Useful generally, not specific to depth investigation.
3. **Depth-walking simulator logic**: v1 proper, about 2-3 days. Deferred until market-filter approach proves insufficient. Algorithm is straightforward; validation against trade-level data is the hard part.

**Methodological note**

The investigation explicitly produced a finding that defers v1 work rather than expanding it. This is by design: the conservative-by-default principle applied to v1 sequencing means doing the cheapest thing that addresses the problem before reaching for more sophisticated infrastructure. Depth walking may genuinely be required later; right now there is a simpler approach to evaluate first.

## Entry 14 — First operational live-resolution event: Eurovision 2026 [ANALYSIS, 2026-05-16]

**Context**

Eurovision Grand Final aired about `21:00-22:30 UTC` on Saturday, 2026-05-16. Pre-show priors recorded around `09:50 EDT` (`13:50 UTC`) showed Italy Top-5 at `0.15-0.20`, which felt anomalously low at the time. Resolution-watcher infrastructure was being deployed during the show; v2 metadata schema landed at `23:29:52 UTC`, after Eurovision markets had already closed and dropped from active tracking. Markets were captured via manual Kalshi API query post hoc.

**Headline finding**

`ITA Top-5` resolved YES from a pre-show implied probability of `15-20%`. Realized return on a flat YES bet at `0.18` would have been about `5.5x`. The market dramatically underpriced Italy's chances.

**Full results**

10 markets observed against pre-show priors where recorded:

- Top-10 markets (8): AUS, ISR, ITA, MOL, DEN, BUL, GRE = YES; ALB = NO.
- Top-5 markets (4): ITA, ISR, BUL = YES; MOL = NO.
- Top-3 markets (1): FRA = NO.

Of the 6 markets with recorded pre-show priors, all 6 resolved YES. This is a small sample, but it is worth noting as a possible pattern: Kalshi Eurovision markets may systematically underprice cultural-favorite positions, particularly in higher-uncertainty buckets such as Top-5.

**Inferred partial Eurovision 2026 final ranking**

- Top 5: ISR, ITA, BUL plus 2 unknown.
- Top 10 additionally: AUS, MOL, DEN, GRE.
- Did not make Top 10: ALB.
- Did not make Top 5: MOL.
- Did not make Top 3: FRA.

**Strategy implications**

One data point is not a strategy, but the ITA Top-5 case is exactly the kind of mispricing pm-edge is designed to detect. If this pattern holds across other low-frequency cultural events, such as Oscars, sports playoffs, and election outcomes, there may be a systematic edge in taking YES on apparent underpricings of established favorites in multi-outcome ranking markets. Track this forward.

**Infrastructure note**

Eurovision missed automatic resolution-watcher capture due to deploy timing artifact: v2 indexer metadata landed after markets closed. Future resolutions are captured automatically once the v2 metadata fields are present. Disappeared-market detection would have caught Eurovision; queue it as Phase 2.1 Sunday/Monday work.

## Usage note

This log is append-only. New entries get a date and a stability tag. Old entries are not edited except to add a "Resolved", "Refuted", or "Superseded" annotation at the top of the section, with a link to the entry that supersedes it. The intent is a faithful record of the reasoning path, including paths that turn out to be wrong, because the wrong paths are diagnostic information about how the project's thinking evolved.

When a research direction matures into something more structured, such as a causal map, a connector implementation, or a strategy variant, it migrates to its own document and this log links to it.
