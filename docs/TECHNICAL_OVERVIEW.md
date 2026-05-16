# pm-edge Technical Overview

This document describes the current pm-edge system as implemented through the forward data-layer deployment. The project is a modular, async-first prediction-market research and paper-trading platform focused on Polymarket, Kalshi, and crypto-heavy market opportunities.

The system is intentionally research- and paper-first. It can fetch markets, generate probability estimates, create edge signals, simulate bets and portfolios, run deep diagnostics, and operate a live paper-trading loop with monitoring. It does not enable real-money execution in the current phase.

## System Goals

pm-edge is built around four core ideas:

- Normalize prediction-market data from multiple venues into one internal representation.
- Estimate fair probability from public information, market microstructure, cross-market relationships, LLM/news context, and crypto/on-chain features.
- Convert probability edge into realistic, risk-constrained paper positions.
- Reject weak strategies through deterministic backtests, deep diagnostics, strict rubrics, and Monte Carlo survival checks before any live-money consideration.

The current strategy direction is liquidity-first and crypto-focused: biased tails, fear-driven setups, neglected sides, and maker-side liquidity are prioritized over unconstrained directional betting. Directional betting remains research-only and stays disabled unless a future holdout backtest clears the rubric.

## Forward Data Layer (Phase 1, deployed)

The forward data layer is the current production data path for future strategy validation. It separates the producer and analysis layers:

- Producer: `scripts/forward_index.py` runs on a DigitalOcean `s-2vcpu-2gb` droplet in TOR1 under systemd. It discovers markets, filters the tradeable universe, maintains book state, emits snapshots every 15 seconds, and writes parquet.
- Wire format: parquet files partitioned by table, `venue`, and UTC `date` under `data/raw/forward_index/`.
- Consumer: parquet is synced from the VPS to the laptop with `deploy/forward_indexer/rsync_to_laptop.sh`.
- Analysis: DuckDB reads the synced parquet locally. The DuckDB query layer is local and does not run on the VPS.

The forward indexer covers both venues with different capture quality:

- Polymarket: discovery uses the Gamma API with active/open filters. Gamma page requests retry transient `429` and `5xx` responses with bounded exponential backoff and abort the current discovery cycle gracefully on hard page failure. Order book state uses CLOB REST initialization plus the public CLOB WebSocket market feed for live book deltas. The validated 23-minute local soak on 200 tracked markets produced 25,600 WebSocket-sourced snapshots and 235 REST-sourced startup snapshots, with memory flat near 334 MB and zero heartbeat errors.
- Kalshi: discovery uses the public REST market data API with `status=open` and a 7-day `max_close_ts` source filter to bound pagination. Book state is REST-refresh-only in the current deployment. REST book parsing uses the observed `orderbook_fp.yes_dollars` and `orderbook_fp.no_dollars` fields first, with legacy field fallbacks retained. The documented Kalshi WebSocket host returns `HTTP 401` without signed API authentication, so signed Kalshi WebSocket capture is deferred.

Discovery uses a liquidity-focused activity filter before subscription. A market enters the tracked set only when all configured checks pass:

- 24h volume is at least `$10,000`.
- Spread is at most `10` cents.
- Recent activity is within the configured recency window.
- Market age is at least `30` minutes when creation time is available.
- Time to close is at least `2` hours when close time is available.

The forward data layer writes three parquet tables:

- `order_book_snapshots`: top-N bid/ask levels, top bid/ask, mid, spread, snapshot source, and timestamp.
- `trade_events`: venue trade id when available, token/outcome id, price, size, side, and timestamp.
- `market_metadata_snapshots`: market status, 24h volume, liquidity, end date, raw venue metadata, and capture timestamp for tracked post-filter markets.

This data path replaces the pre-existing historical signal files as the basis for future strategy validation. See [Data Quality Lessons](DATA_QUALITY_LESSONS.md) for the account of why the legacy `signals_*.parquet` datasets cannot support strategy approval.

## Technology Stack

The repo is a Python research system with production-style boundaries rather than a trading bot wired directly to real money.

- Runtime: Python 3.11+ with async I/O through `asyncio` and `httpx`.
- Packaging: `pyproject.toml` with hatchling/uv-compatible editable installs.
- Configuration: Pydantic v2 and `pydantic-settings`, loaded from `.env` through `src/core/config.py`.
- Dataframes and storage: pandas, numpy, pyarrow/parquet, SQLModel, SQLite locally, and Postgres/Supabase-style database URLs for deployed persistence.
- Market access: PMXT as the preferred unified client path, with direct Polymarket CLOB and Kalshi adapter fallbacks.
- Modeling: scikit-learn and LightGBM-style GBDT models with deterministic walk-forward training, calibration hooks, and feature-importance output.
- LLM processing: local Ollama by default, configured for `qwen2.5:32b`, with optional OpenAI, Claude, or Grok fallback paths for high-value calls.
- News and external data: NewsAPI/GDELT/RSS-style ingestion, VADER fallback sentiment, DefiLlama/Dune/Arkham-style on-chain hooks, and deterministic proxy features when provider data is sparse.
- Risk and simulation: fractional/quarter Kelly sizing, post-cost edge gates, liquidity caps, adverse-selection buffers, Monte Carlo ruin simulation, and Go/No-Go rubrics.
- Monitoring: loguru/structlog logging, Streamlit dashboard, console/webhook alerts, optional async Telegram notifications.
- Quality gates: pytest, ruff, black, mypy.

## Architecture

The repository is organized by responsibility:

```text
src/
  core/          Config, SQLModel schema, market client facade, scanner
  data/          Database, poll/news/on-chain/LLM processors, resolved backfill
  data/forward_indexer/
                 Forward indexer producer: discovery, filtering, WebSocket subscription,
                 REST refresh, book state, snapshot emit, parquet writer
  features/      Feature store, cross-market, advanced, fear, on-chain, micro-round features
  models/        Baselines, LightGBM wrappers, walk-forward trainer
  strategies/    Edge detector, liquidity provider, structural scanner
  execution/     Paper trading, portfolio sizing, risk engine
  backtesting/   Signal, portfolio, deep-analysis, metrics, rubric
  monitoring/    Alerts, Telegram, Streamlit dashboard, performance tracker
  utils/         Logging and shared utilities
scripts/         CLI entrypoints
deploy/          VPS deployment artifacts
notebooks/       Analysis templates
tests/           Unit and integration-style tests
```

The major data flow is:

```text
Market venues / data providers
  -> unified client and data processors
  -> feature store
  -> edge detector / liquidity / structural scanners
  -> portfolio allocator and risk engine
  -> backtester or live paper trader
  -> metrics, dashboard, alerts, reports
```

The forward data-layer flow is separate from the legacy signal-generation flow:

```text
Polymarket Gamma/CLOB + Kalshi REST
  -> src/data/forward_indexer/
  -> in-memory BookState
  -> 15-second snapshot emit
  -> partitioned parquet on VPS
  -> rsync to laptop
  -> DuckDB analysis
```

## Deployment Artifacts

`deploy/forward_indexer/` contains the producer deployment assets:

- `setup_vps.sh`: provisions a fresh Ubuntu 24.04 droplet, creates the `pmedge` user, installs system dependencies and `uv`, clones the repo, creates the virtual environment, installs the package, copies `.env.example`, installs the systemd unit, and starts the service.
- `systemd/forward-indexer.service`: runs `scripts.forward_index` as the non-root `pmedge` user and restarts on failure.
- `rsync_to_laptop.sh`: pulls completed parquet parts from the VPS into `$PM_EDGE_LOCAL_FORWARD_INDEX_DIR`, falling back to local `data/raw/forward_index/`, using rsync size/mtime checks and `--partial`.

The setup script currently requires `PM_EDGE_GIT_REMOTE` to be set to the real repository URL. Its default contains a `YOURUSERNAME` placeholder.

## Configuration and Runtime

Configuration lives in `src/core/config.py` and is loaded with Pydantic Settings using the `PM_EDGE_` environment-variable prefix. `.env.example` documents the expected keys.

Key configuration areas:

- Venue credentials: Polymarket and Kalshi API settings.
- Data providers: NewsAPI/GDELT, LLM providers, DefiLlama/Dune/Arkham-style hooks.
- Runtime safety: paper-trading mode, virtual capital, order caps, review thresholds.
- Telegram: optional bot token, chat id, enable flag, rate limit.
- Strategy controls: fear layer, liquidity-harvest mode, quarter Kelly, post-cost edge floor, adverse-selection buffers, cash buffer, Telegram settings.

The project uses Python 3.11+, hatchling packaging, and dev tooling through `pyproject.toml`. On macOS/Homebrew Python, install inside a virtual environment or via `uv`; do not install into the externally managed system environment.

## Core Market Layer

### Unified Client

`src/core/client.py` defines the async `PredictionMarketClient` facade. It is designed to use PMXT first when available, with direct Polymarket and Kalshi adapters as fallbacks. The client exposes a common interface for:

- Fetching markets.
- Fetching order books.
- Placing orders through the abstract interface.
- Reading positions.

The client boundary is designed to be easy to mock, which is why the tests exercise mocked PMXT/direct SDK behavior rather than requiring network access.

### Domain Models

`src/core/models.py` defines SQLModel tables and enums for the core domain:

- `Market`
- `MarketPrice`
- `Resolution`
- `Position`
- `Trade`
- `Venue`

These models support SQLite locally and Postgres/Supabase-style deployments through SQLModel-compatible connection strings.

### Market Scanner

`src/core/scanner.py` provides a one-pass scanner and cross-venue arbitrage detector. It fetches market snapshots, normalizes them, and identifies basic pricing opportunities that clear a minimum edge threshold.

## Data and Feature Pipeline

### Polls and News Sentiment

`src/data/poll_aggregator.py` normalizes polling data by source, event, date, sample size, and pollster quality. It supports aggregate lookup and historical series generation.

`src/data/news_sentiment.py` ingests news from configurable sources and computes lightweight sentiment and velocity features:

- Mention count.
- Sentiment score.
- Tone shift.
- 24h/7d velocity.
- Keyword/entity links to markets.

### Advanced LLM News Processor

`src/data/llm_news_processor.py` adds optional LLM-based summarization and probabilistic signal extraction. It is provider-configurable and defaults to local Ollama for normal news summarization and sentiment reasoning. Frontier model providers can be configured as fallback paths for high-value calls.

The processor includes:

- Article hashing and cache keys to avoid repeated cost.
- Prompt/response audit records for debugging.
- Rate limiting and batch cost estimation.
- Structured outputs for key events, sentiment, momentum, uncertainty, impact, and probability.
- Lexical fallback behavior when LLM calls are disabled or fail.

### On-Chain Processor

`src/data/onchain_processor.py` supports crypto-specific feature hooks. It links crypto markets to assets and normalizes on-chain or market-flow style observations such as:

- Funding momentum.
- Whale flow.
- TVL changes.
- Volume changes.
- Panic/reversion-style signals.

The module degrades safely when provider credentials or live data are unavailable.

### Feature Store

`src/features/feature_store.py` combines core feature groups into a single feature vector. It can include:

- Poll aggregates.
- News/sentiment features.
- Cross-market features.
- Market microstructure.
- Historical resolution stats.
- Optional advanced LLM/on-chain features.
- Optional fear-layer outputs.
- Optional enhanced on-chain, market-temperature, and micro-round features.

`src/features/advanced_features.py` flattens LLM, on-chain, cross-source agreement, and temporal velocity features into model-ready fields.

`src/features/onchain_enhanced.py` adds deterministic crypto-flow features that can consume real provider fields when available and fall back to stable proxies otherwise:

- Whale-flow velocity.
- Smart-money cluster score.
- Funding-rate momentum and basis pressure.
- Open-interest surge and liquidation-cascade risk.
- TVL / volume deltas.
- Address-cluster activity.
- Panic-reversion score.

`src/features/micro_round.py` adds short-duration market features:

- 5-15 minute market detection.
- YES/NO price-sum excess.
- Incentive multiplier proxy.
- Maker-advantage score.
- Adverse-fill risk.
- 8-12c tail-zone marker.

## Probability Models and Edge Detection

### Baselines

`src/models/baselines.py` implements deterministic baseline models:

- Logistic regression.
- Ridge regression.
- IC-weighted factor combination.

The baselines are intended to provide interpretable reference probabilities and prevent over-reliance on complex models.

### GBDT Model

`src/models/gbdt.py` wraps LightGBM-style probability modeling with time-series-safe calibration support. It supports feature importance output and deterministic training paths for backtesting.

`src/models/trainer.py` provides the production training path for historical signals:

- Walk-forward splits with no future labels in training.
- Feature flattening from nested signal feature dictionaries.
- Binary LightGBM training with calibration support.
- Model, metadata, and feature-importance artifacts.
- Reproducible training through deterministic defaults.

### Edge Detector

`src/strategies/edge_detector.py` defines `EdgeSignal`, the central signal object used downstream. An edge signal contains:

- `market_id`
- Market-implied probability.
- Model-implied probability.
- Edge.
- Confidence.
- Reasoning strings.
- Feature contributions.

The detector combines feature vectors, baselines, optional GBDT-style model output, and optional advanced/enhanced feature adjustments. Fear-layer contribution handling lets high-fear setups influence signal strength and sizing downstream.

## Fear Layer, Liquidity, and Hybrid Strategy

### Fear Layer

`src/features/fear_layer.py` implements the market-temperature router and enhanced fear feature group.

Inputs include:

- Global fear proxies such as VIX, CNN Fear & Greed, crypto fear/greed indices, on-chain panic, and funding stress.
- Per-market liquidity, spread, volume, and attention proxies.

Outputs include:

- `fear_score`
- `market_temperature`
- `effective_attention`
- `fear_sizing_multiplier`
- `fear_route`
- `fear_temperature_interaction`
- regime flags such as high-fear and high-temperature.

The temperature definition is intentionally simple: market temperature rises as effective liquidity/attention falls. This helps route the system toward neglected or fear-driven markets while still giving the allocator a sizing multiplier rather than an unconditional trade instruction.

### Liquidity Harvester

`src/strategies/liquidity_provider.py` implements a conservative liquidity-first strategy. It evaluates market snapshots for:

- Biased-tail No-sale opportunities where No trades around 88-98 cents and the model sees lower true tail risk.
- Both-sides quoting opportunities in short crypto micro-rounds when combined prices are rich enough after buffer.
- Maker-side opportunities with sufficient spread, liquidity, and incentive score.

The harvester applies:

- Minimum spread.
- Minimum liquidity.
- Maximum adverse-selection score.
- Minimum post-fee edge.
- Maker-fee adjustment.
- A 20% adverse-selection haircut in backtest PnL.

The output is a `LiquidityOpportunity` with quote guidance, post-fee edge, adverse-selection score, max notional, and a `should_quote` decision.

### Structural Scanner

`src/strategies/structural_scanner.py` implements lightweight structural checks:

- Sum-less-than-one opportunities in linked clusters.
- Sum-greater-than-one opportunities in linked clusters.
- Depth-gated trade eligibility.

This is intentionally simple and conservative. It is a scanner for inconsistencies, not a full theorem prover.

## Portfolio Construction and Risk

### Fractional Kelly Portfolio

`src/execution/portfolio.py` converts edge signals into target paper positions. The allocator enforces:

- Minimum edge.
- Minimum confidence.
- Max position weight.
- Max total exposure.
- Liquidity fraction caps.
- Correlation penalty.
- Optional quarter Kelly.
- Optional minimum cash buffer.
- Optional post-cost edge threshold.

Strict gates are opt-in through the hardened path: `--quarter-kelly`, post-cost edge controls, adverse-selection buffers, and cash/exposure caps. This preserves earlier paper/backtest behavior unless the liquidity-first risk mode is explicitly enabled.

### Hardened Risk Engine

`src/execution/risk_engine.py` adds the hardened strategy risk layer:

- `HardenedRiskConfig` documents non-negotiable controls such as 5-point post-cost edge, 30% cash buffer, 8-12% event-cluster exposure cap, 20% adverse-selection buffer, and quarter Kelly.
- `MonteCarloRuinSimulator` bootstraps realized PnL paths and estimates ruin probability, median final equity, and 5th/95th percentile final equity.

Monte Carlo diagnostics are saved with every portfolio deep-backtest run.

## Historical Signals, Backtesting, and Evaluation

### Signal Generation

`scripts/generate_signals.py` is the main historical signal generator. It writes a single flat parquet file by default and enforces a complete signal schema for downstream backtests.

Important capabilities:

- Active or resolved market signal generation.
- Crypto-only and volume-filtered runs.
- Outcome joins through `--include-outcomes`.
- Historical CLOB price joins through `--use-historical-prices`.
- Lookahead marking with `is_lookahead` when resolved prices have to be used as a fallback.
- Feature selection through `--feature-set base|advanced|enhanced`.
- Walk-forward model training through `--train-model`.

Example:

```bash
python -m scripts.generate_signals \
  --crypto-only \
  --include-outcomes \
  --use-historical-prices \
  --feature-set enhanced \
  --train-model \
  --start-date 2025-01-01 \
  --end-date 2026-04-02 \
  --output data/processed/signals_crypto_2025_ytd_enhanced_trained.parquet \
  --overwrite
```

### Signal Backtester

`src/backtesting/backtester.py` simulates independent bets from historical signal rows. It handles:

- Date filtering.
- Edge thresholding.
- Venue fee assumptions.
- Slippage.
- PnL and return calculation.
- Metrics/rubric evaluation.

### Portfolio Backtester

`src/backtesting/portfolio_backtester.py` simulates periodic rebalancing from historical signals using the Kelly allocator. It tracks:

- Target positions.
- Period PnL.
- Equity curve.
- Turnover.
- Exposure.
- Portfolio Sharpe, Calmar, drawdown, and return.

### Deep Backtest

`scripts/deep_backtest.py` is the main research runner. It supports:

- Base vs advanced feature comparisons.
- Enhanced feature-set runs from generated signal files.
- Crypto-only filtering.
- Portfolio simulation.
- Hybrid mode with directional plus liquidity-harvest PnL.
- Liquidity-only mode with directional betting disabled.
- Fear layer.
- Quarter Kelly.
- Minimum post-cost edge.
- Relaxed diagnostic mode and rejection breakdowns.
- Monte Carlo ruin simulation.
- Structured output folders with signals, trades, equity curves, metrics, rubrics, calibration data, and analysis tables.

Example:

```bash
python -m scripts.deep_backtest \
  --signals data/processed/signals_crypto_2025_ytd_enhanced_trained.parquet \
  --crypto-only \
  --portfolio \
  --mode hybrid \
  --quarter-kelly \
  --kelly-fraction 0.25 \
  --max-exposure 0.12 \
  --min-edge 0.08 \
  --adverse-buffer 0.25 \
  --max-tail-exposure 0.06
```

### Deep Analysis

`src/backtesting/deep_analysis.py` generates the diagnostic layer:

- Feature contribution ablation.
- Calibration analysis.
- Edge decay curves.
- Category performance.
- Regime analysis.
- Confidence vs accuracy.
- Turnover, slippage, and capacity analysis.
- Failure case studies.
- Feature predictiveness.
- Feature importance stability.
- Rubric failure analysis.
- Bootstrap confidence intervals.
- A/B/C recommendations.

`scripts/generate_report.py` turns deep-backtest output into Markdown or HTML. The report includes summary tables, equity curves, feature diagnostics, failure analysis, recommendations, bootstrap intervals, and retail-capital projections gated by Go/No-Go status.

## Live Paper Trading and Monitoring

### Paper Trader

`src/execution/paper_trader.py` runs the live paper loop. It:

- Fetches active high-volume markets.
- Generates edge signals.
- Computes Kelly target positions.
- Compares targets to current paper state.
- Writes paper decisions and audit logs.
- Supports review mode for large edges.
- Persists state to local JSON.

The current implementation is paper-only. It does not place real exchange orders.

### Monitoring

`src/monitoring/performance_tracker.py` tracks live performance against rubric-like thresholds and flags degradation such as calibration drift or worsening Brier score.

`src/monitoring/dashboard.py` provides a Streamlit dashboard over local paper-trading state and audit files. It shows open positions, equity, top opportunities, recent trade logs, and rubric status.

`src/monitoring/alerts.py` supports console and webhook-style alerts.

`src/monitoring/telegram_alerts.py` provides optional async Telegram notifications for:

- Liquidity opportunities.
- High-edge review mode.
- High-fear setups.
- Risk/degradation alerts.
- Daily performance summaries.

Telegram is disabled unless configured through `.env`.

## CLI Entry Points

The main scripts are:

- `scripts/forward_index.py`: run the forward indexer producer locally or under systemd.
- `scripts/scan.py`: scan venues for market and arbitrage opportunities.
- `scripts/edge.py`: rank markets by edge score.
- `scripts/backtest.py`: run deterministic signal/portfolio backtests.
- `scripts/backfill_polymarket.py`: backfill resolved/active Polymarket data and historical CLOB prices.
- `scripts/generate_signals.py`: generate complete historical signal parquet files.
- `scripts/train_model.py`: train GBDT models from historical signal files.
- `scripts/deep_backtest.py`: run base/advanced/hybrid deep backtests.
- `scripts/generate_report.py`: generate Markdown/HTML reports.
- `scripts/live_paper.py`: run live paper trading.
- `scripts/liquidity_backtest.py`: backtest liquidity-providing opportunities.
- `scripts/paper_trade.py`: submit deterministic local paper trades.

Console scripts are configured in `pyproject.toml` for installed environments.

## Testing and Quality

The test suite covers:

- Client fallbacks and mocked market access.
- SQLModel/database behavior.
- Poll/news/on-chain/LLM processors.
- Feature generation.
- Edge detection.
- Signal and portfolio backtesting.
- Deep analysis and report generation.
- Paper trader behavior.
- Telegram no-op behavior.
- Fear/risk/liquidity/structural components.
- Enhanced on-chain and micro-round feature modules.

Quality gates:

```bash
pytest
ruff check .
black --check src scripts tests
mypy .
```

At the time of the forward data-layer update, the full suite passed with 100 tests. The remaining warnings are from small synthetic fixtures and third-party libraries.

## Current Limitations

The project has a deployed forward data layer, but strategy validation remains blocked on accumulated clean data and a simulator that consumes captured order books:

- Kalshi WebSocket capture requires signed API authentication and is not implemented in Phase 1. Kalshi currently operates in REST-refresh-only mode, so it captures periodic book state rather than real-time WebSocket deltas.
- Polymarket book subscription tracks YES tokens. NO-side book state is not independently tracked. In binary markets, the NO side is derivable from the YES complement, but the independent NO book and its spread are not captured in this phase.
- Polymarket recency filtering uses `updatedAt` as a fallback because Gamma does not expose a guaranteed last-trade timestamp in the fields used by the indexer. On Polymarket, the recency check is effectively a stale-update check. Volume and spread thresholds carry most of the liquidity-filtering load.
- `deploy/forward_indexer/setup_vps.sh` contains a known deployment footgun: the default `PM_EDGE_GIT_REMOTE` value contains a `YOURUSERNAME` placeholder. The script must be run with `PM_EDGE_GIT_REMOTE` set, or the code must be placed manually at `/opt/pm-edge` before installing the service. The fix is deferred.
- The signals-pipeline dataset that pre-dated the forward indexer is not suitable for strategy validation. See [Data Quality Lessons](DATA_QUALITY_LESSONS.md) for the full account.
- Live money execution is intentionally absent.
- LLM and on-chain features remain optional and behind cost/data-quality controls.
- Fear features need real historical fear time series before they can be evaluated as a sizing input.
- Micro-round validation needs actual short-duration market metadata and both-side order-book history.

## Current Verdict

The Phase 1 forward data layer is deployed and producing real WebSocket-sourced data for Polymarket and REST-refreshed data for Kalshi.

The legacy signals dataset cannot support strategy validation, regardless of model or risk-engine quality. Conclusions drawn from backtests on that dataset are not informative because the data contains lookahead fallback contamination, candle-derived price inputs rather than order-book state, noisy activity filtering, unverifiable LLM temporal leakage risk, unmodeled resolution risk, and row-level sample-size inflation.

Real strategy validation now waits on:

- At least 30 days of clean forward capture.
- Signed Kalshi WebSocket authentication or an explicit decision to treat Kalshi as REST-only for the first simulator phase.
- A new execution simulator that consumes captured book state and produces realistic fill estimates against historical resting quotes.
- Per-market resolution accounting and pre-registered Go criteria.

Real-money execution remains explicitly out of scope. The system stays paper-only until forward-captured data and simulator-backed validation clear the rubric.
