# pm-edge Technical Overview

This document describes the current pm-edge system as implemented through Phase 8. The project is a modular, async-first prediction-market research and paper-trading platform focused on Polymarket, Kalshi, and crypto-heavy market opportunities.

The system is intentionally research- and paper-first. It can fetch markets, generate probability estimates, create edge signals, simulate bets and portfolios, run deep diagnostics, and operate a live paper-trading loop with monitoring. It does not enable real-money execution in the current phase.

## System Goals

pm-edge is built around four core ideas:

- Normalize prediction-market data from multiple venues into one internal representation.
- Estimate fair probability from public information, market microstructure, cross-market relationships, LLM/news context, and crypto/on-chain features.
- Convert probability edge into realistic, risk-constrained paper positions.
- Reject weak strategies through deterministic backtests, deep diagnostics, strict rubrics, and Monte Carlo survival checks before any live-money consideration.

The latest strategy direction is liquidity-first and crypto-focused: biased tails, fear-driven setups, neglected sides, and maker-side liquidity are prioritized over unconstrained directional betting.

## Architecture

The repository is organized by responsibility:

```text
src/
  core/          Config, SQLModel schema, market client facade, scanner
  data/          Database, poll/news/on-chain/LLM processors, resolved backfill
  features/      Feature store, cross-market features, advanced features, fear layer
  models/        Baselines and LightGBM probability wrappers
  strategies/    Edge detector, liquidity provider, structural scanner
  execution/     Paper trading, portfolio sizing, risk engine
  backtesting/   Signal, portfolio, deep-analysis, metrics, rubric
  monitoring/    Alerts, Telegram, Streamlit dashboard, performance tracker
  utils/         Logging and shared utilities
scripts/         CLI entrypoints
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

## Configuration and Runtime

Configuration lives in `src/core/config.py` and is loaded with Pydantic Settings using the `PM_EDGE_` environment-variable prefix. `.env.example` documents the expected keys.

Key configuration areas:

- Venue credentials: Polymarket and Kalshi API settings.
- Data providers: NewsAPI/GDELT, LLM providers, DefiLlama/Dune/Arkham-style hooks.
- Runtime safety: paper-trading mode, virtual capital, order caps, review thresholds.
- Telegram: optional bot token, chat id, enable flag, rate limit.
- Phase 8 controls: fear layer, liquidity-harvest mode, quarter Kelly, post-cost edge floor.

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

`src/data/llm_news_processor.py` adds optional LLM-based summarization and probabilistic signal extraction. It is provider-configurable for OpenAI, Claude, or Grok-style APIs through settings.

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

`src/features/advanced_features.py` flattens LLM, on-chain, cross-source agreement, and temporal velocity features into model-ready fields.

## Probability Models and Edge Detection

### Baselines

`src/models/baselines.py` implements deterministic baseline models:

- Logistic regression.
- Ridge regression.
- IC-weighted factor combination.

The baselines are intended to provide interpretable reference probabilities and prevent over-reliance on complex models.

### GBDT Model

`src/models/gbdt.py` wraps LightGBM-style probability modeling with time-series-safe calibration support. It supports feature importance output and deterministic training paths for backtesting.

### Edge Detector

`src/strategies/edge_detector.py` defines `EdgeSignal`, the central signal object used downstream. An edge signal contains:

- `market_id`
- Market-implied probability.
- Model-implied probability.
- Edge.
- Confidence.
- Reasoning strings.
- Feature contributions.

The detector combines feature vectors, baselines, optional GBDT-style model output, and optional advanced feature adjustments. Phase 8 adds fear-layer contribution handling so high-fear setups can influence signal strength and sizing downstream.

## Phase 8 Fear Layer and Hybrid Strategy

### Fear Layer

`src/features/fear_layer.py` implements the market-temperature router.

Inputs include:

- Global fear proxies such as VIX, CNN Fear & Greed, and crypto fear/greed indices.
- Per-market liquidity, spread, volume, and attention proxies.

Outputs include:

- `fear_score`
- `market_temperature`
- `effective_attention`
- `fear_sizing_multiplier`
- `fear_route`

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

Phase 8 gates are opt-in through the strict path: `--quarter-kelly` and `--min-post-cost-edge`. This preserves earlier paper/backtest behavior unless the liquidity-first risk mode is explicitly enabled.

### Hardened Risk Engine

`src/execution/risk_engine.py` adds the Phase 8 risk layer:

- `HardenedRiskConfig` documents non-negotiable controls such as 5-point post-cost edge, 30% cash buffer, 8-12% event-cluster exposure cap, 20% adverse-selection buffer, and quarter Kelly.
- `MonteCarloRuinSimulator` bootstraps realized PnL paths and estimates ruin probability, median final equity, and 5th/95th percentile final equity.

Monte Carlo diagnostics are saved with every portfolio deep-backtest run.

## Backtesting and Evaluation

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
- Crypto-only filtering.
- Portfolio simulation.
- Hybrid mode with directional plus liquidity-harvest PnL.
- Fear layer.
- Quarter Kelly.
- Minimum post-cost edge.
- Monte Carlo ruin simulation.
- Structured output folders with signals, trades, equity curves, metrics, rubrics, calibration data, and analysis tables.

Example:

```bash
python -m scripts.deep_backtest \
  --period 2025-01-01:2026-05-01 \
  --signals data/processed/signals \
  --strategy hybrid_v1 \
  --crypto-only \
  --use-advanced-features \
  --portfolio \
  --mode hybrid \
  --fear-layer-enabled \
  --quarter-kelly \
  --min-post-cost-edge 0.05
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

- `scripts/scan.py`: scan venues for market and arbitrage opportunities.
- `scripts/edge.py`: rank markets by edge score.
- `scripts/backtest.py`: run deterministic signal/portfolio backtests.
- `scripts/generate_signals.py`: generate historical signal parquet partitions.
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
- Fear/risk/liquidity/structural Phase 8 components.

Quality gates:

```bash
pytest
ruff check .
black --check src scripts tests
ruff format --check src scripts tests
mypy src scripts
```

At the time this document was added, the full test suite passed with 41 tests and one benign pandas constant-correlation warning in a small fixture.

## Current Limitations

The project is structurally complete through Phase 8, but real strategy approval still depends on higher-quality historical data:

- The deterministic demo fixture is not enough for a real capital decision.
- The current Go/No-Go rubric correctly rejects small positive samples.
- Real 2025+ historical signal generation requires configured data backfills.
- Live money execution is intentionally absent.
- LLM and on-chain features are optional and should remain behind cost and data-quality controls.
- Liquidity-harvest results must be validated with realistic maker/taker fees, slippage curves, fill assumptions, and adverse-selection buffers on a larger sample.

## Current Verdict

The strongest path is crypto-specialized, liquidity-first paper trading and backtesting:

- Continue using strict rejection thresholds.
- Keep quarter Kelly and minimum 30% cash buffer in Phase 8 mode.
- Require at least a 5-point post-fee/impact edge.
- Keep the liquidity harvester conservative and cluster-capped.
- Run Monte Carlo ruin simulation after every material strategy change.
- Treat any positive demo result as research-only until a fresh, larger holdout clears the rubric.

The latest demo hybrid run improved simulated PnL and Monte Carlo survival, but the rubric still returned `Fail / No-Go` due sample size. The correct next step is a real crypto-focused historical backfill and deep backtest before increasing paper size or considering live-money architecture.
