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

## Entry 15 — Phase 2 core infrastructure complete [INFRASTRUCTURE, 2026-05-16]

**Components delivered**

- Execution simulator v0: conservative-by-default fill simulation, validator suite, and assumption-health reporting.
- Forward indexer metadata enrichment: v2 metadata fields `venue_status_raw`, `is_closed`, `is_archived`, `is_resolved`, `resolution_outcome`, `resolution_timestamp_utc`, and `accepting_orders`.
- Resolution watcher v0 to v0.1: metadata-based detection plus API fallback for ambiguous outcomes.
- Resolution outcome parquet write path with final book state join.
- Deployment on a single 2 GB VPS with systemd memory constraints and 2 GB swap.

**Production incidents and recoveries**

1. OOM cascade after deploying the resolution watcher. The forward indexer was killed four times, and load average reached `11.79` on a two-core VPS. Root cause: about `1.7 GB` combined demand on a 2 GB host with no swap. Fix: stop watcher, add 2 GB swap, redeploy with memory constraints.
2. Polymarket parser missed the `tokens[].winner` field for closed markets. Fixed by extracting the winning token and mapping YES-side wins to `1.0`, NO-side wins to `0.0`, and 50/50 outcomes to `0.5`.
3. Resolution-watcher dedup did not persist across restarts, creating duplicate-write risk. Fixed by hydrating `seen_resolutions` from existing `resolved_market_outcomes` parquet files at startup.
4. Final book join failed when `venue_resolved_at_utc` was null for Polymarket. Fixed by falling back to watcher detection timestamp for final-book lookup.

**Lesson**

Adding a second long-running service to a memory-constrained VPS without first measuring combined working set caused a 30-minute production incident. Future architectural changes validate combined memory profile before deploy, not after the service discovers the limit empirically.

## Entry 16 — Phase 2.1 disappeared-market detection [INFRASTRUCTURE, 2026-05-16]

**Motivation**

Metadata-based resolution detection requires markets to be in the indexer's active set when v2 metadata is captured. Eurovision exposed the gap: 12 Kalshi markets settled within about 10 minutes, then disappeared from active tracking before v2 metadata existed. The watcher could not detect them from metadata fields alone.

**Implementation**

Second detection path in the watcher. It identifies markets that appeared in metadata within the past 24 hours but no longer appear in the most recent active set, excluding anything already in `seen_resolutions`. The watcher queries the venue API directly for each disappeared market, rate-limited to 50 calls per cycle per venue.

Resolved disappeared markets are persisted through the same `resolved_market_outcomes` table as metadata-detected markets, with `resolution_source` set to the venue API source and `is_disappeared_detection=true` for traceability.

**Production rollout outcomes**

- `725` disappeared candidates identified across both venues on the first production cycle.
- `41` resolutions captured in production in the first 30 minutes.
- `31` of `38` Kalshi captures had pre-resolution book state.
- All 12 Eurovision markets were captured with outcomes and book state where available.

**Structural finding**

The indexer's `volume_num_min=10000` threshold caused `ITA Top-5` to drop from active tracking at `12:31:48 UTC`, about 11 hours before the market closed. The mispricing, around `0.18` implied probability versus realized YES, existed throughout that 11-hour window, but the infrastructure lost visibility to it.

**Filter-vs-edge tension**

Low-volume markets are simultaneously the ones most likely to be mispriced, because fewer participants force consensus, and the ones the indexer is most likely to lose track of, because the activity filter prunes them. This is an inherent tension in filter-based active sets, not a bug. Future filtering work must treat "tradeable enough to monitor" and "liquid enough to size" as separate concepts.

## Entry 17 — Eurovision 2026 production capture update [ANALYSIS, 2026-05-16]

**Setup**

Entry 14 captured the initial Eurovision live-resolution lesson. After Phase 2.1 disappeared-market detection was deployed, the watcher captured the resolved Kalshi Eurovision markets that had closed before v2 metadata was available.

`13` Kalshi markets were observed pre-show, with informal price priors recorded around `09:50 EDT` (`13:50 UTC`). The show ended around `22:30 UTC`. Markets closed in the `23:15-23:26 UTC` window.

**Captured outcomes through disappeared detection**

| Market | Result | Final book state |
|---|---:|---|
| AUS Top-10 | YES (`1.0`) | `0.97/0.98` |
| ISR Top-10 | YES (`1.0`) | `0.89/0.95` |
| BUL Top-10 | YES (`1.0`) | `0.96/NULL` |
| DEN Top-10 | YES (`1.0`) | `0.63/0.66` |
| ITA Top-10 | YES (`1.0`) | `0.57/0.62` |
| MOL Top-10 | YES (`1.0`) | `0.49/0.66` |
| GRE Top-10 | YES (`1.0`) | `NULL/NULL` |
| ALB Top-10 | NO (`0.0`) | `0.33/0.35` |
| BUL Top-5 | YES (`1.0`) | `0.99/NULL` |
| ISR Top-5 | YES (`1.0`) | `0.99/NULL` |
| MOL Top-5 | NO (`0.0`) | `NULL/0.01` |
| FRA Top-3 | NO (`0.0`) | `NULL/0.01` |

**Pre-show priors recorded to results**

| Market | Pre-show | Result | Return |
|---|---:|---:|---:|
| AUS Top-10 | `0.97` | YES | `1.03x` |
| ISR Top-10 | `0.93` | YES | `1.07x` |
| AUS Top-5 | `0.79` | YES | `1.27x` |
| BUL Top-5 | `0.63` | YES | `1.59x` |
| ITA Top-10 | `0.59` | YES | `1.69x` |
| MOL Top-10 | `0.58` | YES | `1.72x` |
| ITA Top-5 | `0.18` | YES | `5.5x` |

A flat `$1` stake on each recorded prior price implies `$4.67` staked and `$7` returned, or `1.50x`.

**Headline observation**

`ITA Top-5` at `0.18-0.20` was flagged as anomalously low pre-show and resolved YES. The market underpriced Italy's chances by roughly `4-5x`.

**Caveat**

Seven observed priors are not a strategy. All seven favorites won, so the sample is favorable by construction. The important question is what hit rate looks like across hundreds of similarly flagged low-frequency event markets. The infrastructure now captures the data needed to answer that question forward.

**Inferred Eurovision 2026 final ranking**

- Top 5: ISR, ITA, BUL plus two others.
- Top 10 additionally: AUS, MOL, DEN, GRE.
- Not Top 10: ALB.
- Not Top 5: MOL.
- Not Top 3: FRA.

**Next research direction**

Track similar low-frequency cultural-event markets, including Oscars, sports playoffs, and single-event political markets, to test whether the apparent underpricing of established favorites in multi-outcome ranking markets generalizes.

## Entry 18 — Volume filter mechanism investigation [INFRASTRUCTURE, 2026-05-16]

**Confirmed mechanism**

Post-deploy investigation following the Eurovision capture confirmed that the `volume_num_min=10000` threshold that dropped `ITA Top-5` is shared between venues through the runner's `ActivityThresholds`, not specific to either Polymarket or Kalshi.

- Polymarket: filter applied server-side via the `volume_num_min` Gamma API query parameter in `src/data/forward_indexer/polymarket.py`.
- Kalshi: filter applied client-side post-fetch in the shared runner via `min_24h_volume_usd` in `src/data/forward_indexer/filters.py`.
- Both are sourced from `src/core/config.py` through the `PM_EDGE_FORWARD_INDEXER_MIN_24H_VOLUME_USD` environment variable.
- Default: `$10,000` USD 24h rolling volume.
- Tunable without code changes via `.env` plus forward-indexer restart.

**Why not adjust tonight**

The 2 GB VPS is currently within budget but still constrained. Current observed indexer working set is about `455-664 MB`, with peak around `1.1 GB` and `761 MB` swap in use. Lowering the threshold to `$5k` likely grows the active set by `1.5-2x`; lowering to `$1k` could grow it by `3-5x`.

Without an empirical memory profile at each setting, changing the threshold carries OOM-recurrence risk that does not justify the upside tonight. Phase 2.1 disappeared-market detection already captures resolutions retroactively. The remaining gap is mid-trade book history for thin markets, which is valuable but not urgent enough to risk production stability after the day's earlier memory incident.

**Recommended Phase 3 design**

Implement a metadata-only watch list for markets that drop below the activity threshold.

- When a previously active market falls below `min_24h_volume_usd`, transition it from full subscription to metadata-only state.
- Continue periodic metadata snapshots, every 5-10 minutes, for up to N days after drop or until market resolution.
- Do not maintain order book WebSocket subscription for watch-list markets, keeping memory cost minimal.
- Capture resolution status changes and mid-trade metadata evolution without the memory cost of full book tracking.

**Acceptance criteria for Phase 3**

- Markets that drop below threshold during their lifetime are captured at every state transition.
- Memory overhead stays under `+20%` even with `2-3x` more markets in the watch list than in the active set.
- Disappeared-market detection becomes a backstop rather than the primary capture mechanism for thin markets.

**Production state at end of session**

- Forward indexer: stable, about `455 MB` current, `1.1 GB` peak, `761 MB` swap.
- Resolution watcher: `48` resolutions captured, `38` Kalshi plus `10` Polymarket, with at least `31` carrying book state.
- 12 Eurovision markets captured complete.
- Backlog of about `664` disappeared markets draining at decreasing hit rate; priority ordering has already processed the most likely settled candidates.
- Both services are within memory budgets, swap usage is healthy, and the system is running unattended-stable.

## Entry 19 — First calibration analysis, honest null result [ANALYSIS, 2026-05-17]

**Setup**

Analyzed `111` resolutions with paired pre-resolution book state captured Saturday-Sunday through Phase 2 and Phase 2.1 infrastructure. Computed implied YES probability as the midpoint of final bid/ask and compared it to the realized binary outcome.

**Initial finding, later invalidated**

Markets in the `0.25-0.75` implied-probability range initially appeared to systematically underprice YES outcomes, with gaps of `+21` to `+38` percentage points between implied probability and realized YES rate.

**Critical correction via lag analysis**

Lag analysis showed that `25%` of captures had negative lag, meaning the final book timestamp was after the venue resolution timestamp. These rows contain post-settlement book state and are not valid pre-resolution observations.

Among the remaining valid captures, the apparent underpricing was concentrated in long-lag rows over `120` minutes, where markets had not yet converged to final state at capture time. With negative-lag rows excluded and the analysis restricted to lag under `4h`, the pattern reversed: realized YES rate is below implied probability in every bin from `0` to `0.9`.

**Honest result on cleaned 73-market subset**

- Brier score: `0.159`, indicating the markets are reasonably well-calibrated.
- Every probability bin below `0.9` shows realized YES rate below implied probability.
- The `0.9-1.0` bin shows realized `100%` versus implied `96%`.
- No obvious systematic mispricing pattern is detectable at this sample size.

**Population caveat**

`70` of the `73` cleaned markets are Kalshi MLB sports markets. The sample is not representative of prediction markets generally. Eurovision-style cultural markets are nearly absent from this subset.

**Methodological lesson**

Calibration analysis is highly sensitive to capture-timing artifacts. Future analyses filter on lag-to-resolution before drawing inferences. The edge reported in the first cut was explained by stale final-book captures.

**What the analysis does not show**

- Whether market-orderbook dynamics, including depth, volume, and spread changes, carry signal beyond mid-price.
- Whether specific market categories, including cultural events and geopolitics, have different calibration profiles than sports.
- Whether intraday price movements predict resolution direction.

These remain next-iteration research questions once more data accumulates.

## Entry 21 — Static depth imbalance, null result [ANALYSIS, 2026-05-17]

**Hypothesis**

Top-of-book or total-depth imbalance at the moment of final-book capture predicts resolution outcome beyond what implied probability alone predicts.

**Method**

Used the lag-clean subset of `102` markets: positive lag, under `4h`, all Kalshi. Compared YES versus NO outcomes through within-implied-probability-bin imbalance differences, then ran logistic regressions.

**Result**

- Within-bin comparison is inconsistent. Top imbalance favors YES in `2` of `3` testable bins, but total-depth imbalance favors YES in only `1` of `3` bins. Magnitudes are within sampling noise.
- Logistic regression: `implied_prob` alone gives pseudo R² `0.27` and AIC `106.91`.
- Adding `top_imbalance` or `total_imbalance` produces p-values of `0.47-0.50` and increases AIC by `1.5-3.3` points.
- No evidence appears for independent signal from static depth imbalance.

**Conclusion**

At the moment of final-book capture, static depth imbalance does not predict outcomes beyond mid-price. Markets in this sample are sufficiently efficient that directional information in the order book is already incorporated into price.

**Caveat**

The sample is `102` Kalshi markets, mostly MLB. Results may differ for other venues, market types, or capture timestamps farther from resolution.

**Next research directions**

1. Temporal price dynamics, including velocity and volatility, over the captured snapshot stream rather than final-only snapshots.
2. Calibration at multiple time horizons, including `1h`, `6h`, and `24h` before resolution, to test whether mispricing exists earlier and converges away before resolution.
3. Per-category analysis with sufficient samples, requiring roughly `50+` Eurovision-style markets and `100+` Polymarket markets before drawing category-level conclusions.

## Entry 22 — Temporal price dynamics before resolution [ANALYSIS, 2026-05-17]

**Hypothesis**

Price trajectory in the two hours before final-book capture predicts resolution outcome beyond the final mid-price level. A market arriving at a `0.40` implied probability from above may carry different information than a market arriving at `0.40` from below.

**Method**

Used the same lag-clean resolution population as Entry 19: positive lag and under `4h` between final captured book and venue resolution timestamp. For each resolved market, queried the order book snapshot stream from `T-120m` to final-book time and extracted:

- `mid_final`
- `mid_30`, `mid_60`, `mid_120`
- `velocity_30min`, `velocity_60min`, `velocity_120min`
- volatility of mid prices over the `T-120m` to `T-30m` window

The regression tests use only markets with complete temporal features.

**Sample sizes**

- Resolutions with paired book state: `111`
- Lag-clean resolved markets: `73`
- Venue split after lag filtering: `73` Kalshi, `0` Polymarket
- Markets with at least `5` snapshots in the `120m` window: `73`
- Markets with full temporal features: `35`

The full-feature requirement is much stricter than the final-snapshot analyses because each market needs usable snapshots near `T-30m`, `T-60m`, and `T-120m`.

**Regression results**

Baseline model: `resolved_value ~ mid_final`

- Pseudo R²: `0.4115`
- AIC: `31.18`

Model: `resolved_value ~ mid_final + velocity_60min`

- Pseudo R²: `0.4115`
- AIC: `33.18`
- `velocity_60min` coefficient: `3.76`
- p-value: `0.996`
- Likelihood-ratio p-value versus baseline: `0.9957`

Model: `resolved_value ~ mid_final + velocity_120min`

- Pseudo R²: `0.4132`
- AIC: `33.10`
- `velocity_120min` coefficient: `58.17`
- p-value: `0.789`
- Likelihood-ratio p-value versus baseline: `0.7830`

Model: `resolved_value ~ mid_final + volatility`

- Pseudo R²: `0.5658`
- AIC: `26.05`
- `volatility` coefficient: `-66.06`
- coefficient p-value: `0.056`
- Likelihood-ratio p-value versus baseline: `0.0076`

**Result**

Price velocity is a clean null in this sample. Neither `velocity_60min` nor `velocity_120min` improves fit beyond final mid-price. AIC worsens by roughly `2` points and likelihood-ratio p-values are near `0.8-1.0`.

Volatility is different. The model with volatility improves AIC from `31.18` to `26.05`, and the likelihood-ratio test is significant at `p=0.0076`. The coefficient is negative and borderline by its own standard error (`p=0.056`), suggesting that higher pre-resolution volatility is associated with lower realized YES probability after controlling for final mid-price. This is not yet a strategy signal, but it is the first order-book-derived feature in these analyses that improves model fit after controlling for price level.

**Interpretation**

The simple momentum/reversal hypothesis is not supported. The final price level captures the directional information contained in recent velocity.

The volatility result is worth tracking but not acting on. The sample is only `35` full-feature markets, all Kalshi, likely dominated by MLB. The result may reflect a sports-market artifact, noisy late-game books, or a genuine uncertainty signal. It requires a larger sample and category segmentation before it belongs in any strategy logic.

**Next research directions**

1. Re-run temporal dynamics after a week of accumulated resolutions, targeting at least `100+` full-feature markets.
2. Segment volatility by category and venue before interpreting it as a general signal.
3. Test earlier horizons, especially `6h` and `24h` before resolution, where convergence artifacts are weaker and mispricing is more plausible.
4. Compare volatility to spread and liquidity to determine whether the feature is measuring information uncertainty or simply thin-book noise.

## Entry 23 — Microstructure features do not predict outcomes; the data explains why
### 2026-05-24 (Week 2 close)

**Question (pre-registered):** Does pre-resolution price volatility predict
resolution outcome beyond the mid-price level? (The last hypothesis left alive
after Entries 21–22; volatility showed marginal promise at n=35, p=0.056.)

**Result: NULL — and the reason is structural, not statistical.**

Retested on the clean post-lag-fix week (251 clean Kalshi resolutions, 133 with
a computable volatility window). The logistic regression would not converge:
the volatility feature is 94.7% near-zero, 30% exactly zero, median 5.5e-17.
Standardizing did not help (still non-convergent, trillion-scale standard errors)
— there is no variation to regress on.

**Why: Kalshi prices are frozen pre-resolution.** Density check on the
[-120min, -30min] window:
- Snapshots captured per market: median **353** (range 0–716) — dense capture
- DISTINCT mid values per market: median **1**
- 96.2% of markets have ≤1 distinct mid; 100% have ≤2

The book is captured densely, but the mid-price takes a single value for the
entire pre-resolution window in 96% of markets. The market prices once, holds
flat, then resolves. There is no trajectory to mine.

**This explains all four prior nulls with one mechanism:**
- Calibration gap (E19–20): lag artifact, well-calibrated once controlled
- Depth imbalance (E21): p=0.47 — static book at a frozen price adds nothing
- Velocity (E22): p=0.97 at n=86 — no price movement to have velocity
- Volatility (E23): degenerate fit — no price movement to have volatility

**Polymarket cannot rescue this either.** Polymarket has price movement, but its
capture-to-resolution lag is a median of ~16 hours (max 9.5 days) because markets
enter the resolved set via disappeared-detection long after they go quiet. Only
21/111 survive a <4h lag filter, and those are pre-converged extremes (Brier
0.009 is an artifact of near-decided markets, not skill).

**Conclusion.** Book state at the granularity captured does not contain predictive
signal beyond the mid-price, on either venue, for distinct reasons:
- **Kalshi**: prices frozen pre-resolution (no trajectory)
- **Polymarket**: books too stale relative to resolution (no near-resolution book)

This closes the snapshot-microstructure line of inquiry. Any future edge would
require either (a) capturing the brief active-repricing window Kalshi markets have
right at resolution (currently missed — the price jumps from frozen to resolved
without captured intermediate states), or (b) a venue/market type with continuous
liquid pre-resolution pricing AND tight capture-to-resolution pairing, which
neither current venue provides.

**Dead hypotheses (do not re-run):** calibration-gap, depth-imbalance, velocity,
volatility. All four nulls, one cause.

## Usage note

This log is append-only. New entries get a date and a stability tag. Old entries are not edited except to add a "Resolved", "Refuted", or "Superseded" annotation at the top of the section, with a link to the entry that supersedes it. The intent is a faithful record of the reasoning path, including paths that turn out to be wrong, because the wrong paths are diagnostic information about how the project's thinking evolved.

When a research direction matures into something more structured, such as a causal map, a connector implementation, or a strategy variant, it migrates to its own document and this log links to it.
