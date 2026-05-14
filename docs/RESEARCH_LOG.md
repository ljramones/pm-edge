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

## Usage note

This log is append-only. New entries get a date and a stability tag. Old entries are not edited except to add a "Resolved", "Refuted", or "Superseded" annotation at the top of the section, with a link to the entry that supersedes it. The intent is a faithful record of the reasoning path, including paths that turn out to be wrong, because the wrong paths are diagnostic information about how the project's thinking evolved.

When a research direction matures into something more structured, such as a causal map, a connector implementation, or a strategy variant, it migrates to its own document and this log links to it.
