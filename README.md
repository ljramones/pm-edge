# pm-edge

**A systematic prediction market trading system** for Polymarket, Kalshi, and related platforms.

Focused on finding and exploiting edge through information aggregation, cross-platform arbitrage, catalyst awareness, and disciplined risk management.

---

## Status

The forward data layer is now deployed for Phase 1 capture. The repo still contains the Phase 0-14 research, modeling, paper-trading, and diagnostics components, but legacy `signals_*.parquet` backtests are not used for strategy approval. Real validation now depends on accumulated forward book data and a new execution simulator that consumes captured order-book state.

For a detailed architecture and implementation walkthrough, see [Technical Overview](docs/TECHNICAL_OVERVIEW.md).

For day-to-day producer monitoring, laptop sync, and notebook workflow, see [Operations Runbook](docs/OPERATIONS.md).

For the data-quality record explaining why the legacy signals dataset was rejected, see [Data Quality Lessons](docs/DATA_QUALITY_LESSONS.md).

For the latest enhanced-feature validation, see [Feature Engineering Impact Report](docs/FEATURE_ENGINEERING_IMPACT_REPORT.md).

Current operational milestone:

- Phase 1 forward indexer deployed: Polymarket WebSocket-sourced book capture, Kalshi REST-refreshed book capture, static ops status page, laptop rsync workflow, and DuckDB notebook analysis against forward parquet data.

---

## Philosophy

- Edge comes from **speed + synthesis** of public information, not from secret signals.
- Robustness and risk control > raw predictive accuracy.
- Pre-registered rubrics, proper backtesting, and conservative sizing.
- Separate from all previous quant research (clean repo).

---

## Finalized Stack

- **Core runtime:** Python 3.11+, async-first architecture, `httpx`
- **Unified market access:** PMXT (`pmxt`) first, with Polymarket CLOB (`py-clob-client-v2`) and Kalshi SDK fallbacks
- **Data and modeling:** pandas, numpy, scikit-learn, LightGBM
- **Persistence:** SQLModel with SQLite for local development and Postgres/Supabase-style deployments
- **Forward data layer:** VPS producer, Polymarket WebSocket book capture, Kalshi REST-refresh capture, partitioned parquet, laptop DuckDB analysis
- **Configuration:** Pydantic v2 + pydantic-settings + `.env`
- **Reliability:** tenacity retries, typed client boundaries, easy-to-mock adapters
- **Logging:** loguru + structlog with contextual structured logs
- **Advanced features:** cached LLM news summaries via local Ollama by default, with OpenAI/Claude/Grok fallbacks, plus crypto on-chain hooks via public HTTP APIs
- **Live monitoring:** paper-only trader loop, persisted audit logs, Streamlit dashboard, optional webhook/Telegram/Discord alerts
- **Telegram alerts:** optional async Telegram notifier with review buttons, liquidity alerts, degradation alerts, and daily summaries
- **Deep analysis:** base-vs-advanced backtest comparisons, calibration, edge decay, regimes, category cuts, failure cases, report generation
- **Phase 8 risk controls:** fear/temperature routing, biased-tail liquidity harvesting, post-cost edge gates, quarter Kelly, cash buffer, and Monte Carlo ruin simulation
- **Phase 14 enhanced features:** deterministic on-chain/flow proxies, bounded fear-temperature features, micro-round maker-advantage diagnostics, and walk-forward GBDT training support
- **Tooling:** hatchling/uv-compatible packaging, black, ruff, mypy, pytest, pytest-asyncio, pre-commit

---

## Features (Planned / Completed)

### Phase 0 - Foundation

- [x] Project scaffold and packaging
- [x] Pydantic settings and `.env.example`
- [x] SQLModel market, price, resolution, position, and trade models
- [x] Async unified client foundation with PMXT-first fallback design
- [x] Structured logging setup
- [x] Unified client integration tests against mocked PMXT / direct SDK adapters
- [x] Real-time market scanner + arbitrage detector
- [x] Historical resolved market database
- [x] Paper trading engine with full logging

### Phase 1 - Core Edge Signals

- [x] Poll aggregation engine
- [x] News + sentiment velocity features
- [x] Cross-market correlation models
- [x] Simple probabilistic baseline models (Logistic / Ridge / IC-weighted)
- [x] LightGBM probability model wrapper
- [x] Unified feature store
- [x] Edge detector and ranked edge CLI

### Phase 2 - Advanced

- [x] Time-series walk-forward split logic
- [x] Deterministic signal backtester with slippage and venue fee assumptions
- [x] Predictive/economic/robustness metrics
- [x] Pre-registered Decision-Grade / Promising / Fail rubric
- [x] Backtest CLI and analysis notebook template

### Phase 3 - Historical Signals + Portfolio Simulation

- [x] Resumable historical signal generation CLI with partitioned parquet output
- [x] Fractional Kelly portfolio allocator with exposure, confidence, liquidity, and correlation controls
- [x] Portfolio backtester with periodic rebalancing, equity curve, turnover, and exposure tracking
- [x] Portfolio-level rubric metrics
- [x] Portfolio analysis notebook template

### Phase 4A - Advanced Feature Engineering

- [x] Cached LLM news processor with provider selection, rate limiting, prompt/response audit cache, cost estimates, and lexical fallback
- [x] Crypto on-chain processor with DefiLlama hooks and safe no-data fallback
- [x] Advanced feature extractor for LLM, on-chain, cross-source agreement, and temporal velocity features
- [x] Optional edge-detector integration controlled by config/CLI flags
- [x] Signal-generation flags for `--use-llm`, `--use-onchain`, and `--llm-provider`
- [x] Advanced feature exploration notebook template

### Phase 4 - Live Paper Trading + Monitoring

- [x] Live paper trading loop with Kelly targets and review mode
- [x] Paper-only state persistence and audit log
- [x] Console plus optional webhook/Telegram/Discord alerts
- [x] Streamlit dashboard for positions, equity, opportunities, trades, and rubric status
- [x] Live performance tracker with degradation flags
- [ ] Live money execution bot with risk limits

### Phase 5 - Deep Backtesting + Comprehensive Analysis

- [x] Deep backtest CLI with base vs advanced run variants
- [x] Portfolio and independent-bet output persistence to structured folders
- [x] Feature contribution ablation, calibration, edge decay, category, regime, confidence, capacity, and failure-case diagnostics
- [x] Extended rubric with significance checks and Go / No-Go constraints
- [x] Markdown/HTML report generator with equity-curve chart
- [x] Deep analysis notebook template

### Phase 6 - Deep Diagnosis + Targeted Iteration

- [x] Per-category, per-regime, and per-feature diagnostic tables
- [x] Failure-case deep dives with feature and news/advanced context
- [x] Feature predictiveness and stability analysis
- [x] Rubric failure-mode classification and strictness recommendation
- [x] A/B/C project recommendation matrix: continue, narrow, or pause
- [x] Notebook sections explaining why the rubric failed and what to test next

### Phase 7 - Multi-Track Iteration + Telegram

- [x] Telegram notifier with optional inline buttons and graceful no-op fallback
- [x] Crypto-only mode for signal generation, live paper, and deep backtesting
- [x] Enhanced crypto features: funding momentum, whale flow, panic reversion
- [x] Resolved-market backfill utility and bootstrap confidence intervals
- [x] LiquidityProvider strategy with adverse-selection detection
- [x] Liquidity backtest CLI with optional Telegram alerts

### Phase 8 - Liquidity-First Hybrid Strategy

- [x] Fear layer and market-temperature router for selection and sizing
- [x] Liquidity harvester for biased-tail No sales and crypto micro-round quoting
- [x] Lightweight structural/Dutch-book scanner for linked-market consistency checks
- [x] Hardened risk engine with 5-point post-cost edge gate, 30% cash buffer, impact-derated quarter Kelly, and cluster exposure caps
- [x] Monte Carlo ruin simulation saved with every portfolio deep backtest
- [x] Hybrid deep-backtest mode with directional plus liquidity-harvest outputs

### Phase 9 - Signal Pipeline Stabilization

- [x] Historical signal generation made stricter about empty outputs and unresolved market data
- [x] Resolved-market and outcome paths normalized around `data/`
- [x] CLI failure modes improved for missing resolved-market parquet and empty backtest inputs
- [x] Legacy signal data quality issues documented as blockers for strategy approval

### Phase 10 - Historical Price Safeguards

- [x] Historical price fallback behavior made explicit with lookahead flags
- [x] Backtest inputs guarded against resolved-price contamination
- [x] Signal-generation and deep-backtest flows updated to reject or filter lookahead-tainted rows
- [x] Data-quality lesson recorded: candle-derived historical prices cannot validate liquidity-harvest execution

### Phase 11 - Local LLM and Real Model Training

- [x] Ollama integrated as the default LLM backend for local news summarization and feature generation
- [x] Default local model set to `qwen2.5:32b`, with configurable high-value fallback model
- [x] `--ollama-model` override added for signal generation
- [x] Walk-forward LightGBM training path added through `scripts/train_model.py` and `--train-model`
- [x] Trained model artifacts and feature-importance outputs saved under `models/`

### Phase 12 - Relaxed Diagnostic Backtesting

- [x] `--relaxed` mode added to `scripts/deep_backtest.py`
- [x] Individual risk override flags added for edge threshold, max exposure, Kelly fraction, and liquidity cap behavior
- [x] Reports clearly mark relaxed runs as diagnostic and not representative of strict risk rules
- [x] Relaxed mode used to inspect raw signal strength separately from production-style risk constraints

### Phase 13 - Liquidity-Only Strategy Focus

- [x] `--mode liquidity-only` added to deep backtest and live paper flows
- [x] Directional betting disabled in liquidity-only mode
- [x] Liquidity harvester hardened with adverse-selection scoring, stricter post-cost edge gates, conservative tail exposure, and reason-code diagnostics
- [x] Liquidity performance reports added with PnL attribution and Go / Promising / No-Go verdicts
- [x] Larger backfill validation showed liquidity-only was narrow and directional hybrid remained No-Go

### Phase 14 - Enhanced Feature Engineering

- [x] Enhanced on-chain features for whale flow, funding momentum, open-interest pressure, and flow imbalance proxies
- [x] Fear and temperature layer expanded with bounded regime and interaction features
- [x] Micro-round features added for duration, spread dynamics, maker advantage, and incentive-style diagnostics
- [x] `--feature-set enhanced` added to signal generation
- [x] Feature engineering impact report recorded that improved features did not rescue the legacy signal dataset

The Phase 9-14 work is retained because it documents what was tried and why the project changed direction. It does not override the current validation stance: legacy `signals_*.parquet` backtests are research artifacts, and real strategy validation now depends on forward-captured book data plus an execution simulator.

---

## Project Structure

```bash
pm-edge/
├── src/
│   ├── core/           # Config, unified client, scanner, arbitrage detection
│   ├── data/           # Persistence, scrapers, poll aggregators, on-chain, news
│   ├── features/       # Feature engineering
│   ├── models/         # Probability models + baselines
│   ├── strategies/     # Arb, sentiment, catalyst strategy modules
│   ├── execution/      # Paper trading, position sizing, risk, portfolio
│   ├── monitoring/     # Alerts, live performance tracking, dashboard
│   ├── backtesting/    # Simulation and evaluation
│   └── utils/          # Logging and shared helpers
├── notebooks/          # Exploration and analysis
├── config/
├── data/               # .gitignore'd
├── scripts/            # CLI commands (scan, trade, backtest)
├── tests/
├── pyproject.toml
├── README.md
└── .env.example
```

Important Phase 0 modules:

- `src/core/client.py` - async `PredictionMarketClient` facade with PMXT-first fallback design
- `src/core/scanner.py` - one-pass scanner and cross-venue arbitrage detector
- `src/core/models.py` - SQLModel tables for markets, prices, resolutions, positions, and trades
- `src/data/database.py` - SQLite/Postgres-compatible historical market store
- `src/execution/paper.py` - in-memory paper trading engine with risk checks and structured logs

Important Phase 1 modules:

- `src/data/poll_aggregator.py` - poll normalization, weighting, persistence, and historical aggregates
- `src/data/news_sentiment.py` - NewsAPI/GDELT adapters, keyword linking, VADER/fallback sentiment, velocity features
- `src/features/cross_market.py` - rolling correlations, divergence, lead-lag, conditional-probability features
- `src/features/feature_store.py` - unified feature vectors across polls, sentiment, market structure, and history
- `src/models/baselines.py` - logistic, ridge, and IC-weighted baseline probability models
- `src/models/gbdt.py` - LightGBM probability model with time-series calibration fallback
- `src/strategies/edge_detector.py` - `EdgeSignal` generation and ranked market scoring

Important Phase 2 modules:

- `src/backtesting/data_split.py` - walk-forward split generation that respects resolution dates
- `src/backtesting/backtester.py` - deterministic signal backtester with venue fees, slippage, PnL, and persistence
- `src/backtesting/metrics.py` - Brier/log-loss, calibration, rank correlation, hit rates, PnL, Sharpe, Sortino, drawdown, and robustness cuts
- `src/backtesting/rubric.py` - fixed evaluation thresholds and multiple-testing note
- `notebooks/backtest_analysis.ipynb` - calibration, PnL, and category analysis template

Important Phase 3 modules:

- `scripts/generate_signals.py` - resumable historical signal generation to partitioned parquet
- `src/execution/portfolio.py` - fractional Kelly allocation with risk and liquidity caps
- `src/backtesting/portfolio_backtester.py` - portfolio rebalancing simulation and equity-curve metrics
- `notebooks/portfolio_analysis.ipynb` - independent-bet vs Kelly portfolio analysis template

Important Phase 4A modules:

- `src/data/llm_news_processor.py` - cached LLM news summaries, probability signals, rate limiting, cost estimates, and fallback scoring
- `src/data/onchain_processor.py` - crypto market linking and normalized on-chain snapshots
- `src/features/advanced_features.py` - advanced feature group flattening for model inputs
- `notebooks/advanced_features_exploration.ipynb` - incremental-value and cost-benefit analysis template

Important Phase 4 modules:

- `src/execution/paper_trader.py` - live paper loop: market fetch, signals, Kelly targets, review gate, persisted state, audit log
- `src/monitoring/performance_tracker.py` - live degradation checks and rubric snapshot
- `src/monitoring/alerts.py` - console and optional webhook/Telegram/Discord alerts
- `src/monitoring/dashboard.py` - Streamlit dashboard over state and audit files
- `scripts/live_paper.py` - `pm-paper-trade` CLI entrypoint

Important Phase 5 modules:

- `scripts/deep_backtest.py` - deep backtest runner and structured artifact writer
- `src/backtesting/deep_analysis.py` - ablation, calibration, decay, regime, confidence, capacity, feature diagnostics, failure cases, and recommendation analysis
- `scripts/generate_report.py` - Markdown/HTML report generation from saved deep-backtest folders
- `notebooks/deep_backtest_analysis.ipynb` - interactive before/after analysis template
- `src/monitoring/telegram_alerts.py` - optional Telegram templates for review, liquidity, risk, and summaries
- `src/strategies/liquidity_provider.py` - market-making rules and simple adverse-selection model
- `src/data/resolved_backfill.py` - local resolved-market backfill loader for sample expansion

Important Phase 8 modules:

- `src/features/fear_layer.py` - global fear and per-market temperature router
- `src/strategies/liquidity_provider.py` - biased-tail and maker-side liquidity harvester with post-fee edge checks
- `src/strategies/structural_scanner.py` - simple sum-less-than-one / sum-greater-than-one consistency scanner
- `src/execution/risk_engine.py` - Monte Carlo ruin simulator and hardened risk settings
- `src/execution/portfolio.py` - quarter-Kelly, cash-buffer, cluster, liquidity, and impact-aware allocation controls

Important Phase 9-10 modules and artifacts:

- `scripts/generate_signals.py` - stricter output validation, historical price safeguards, and lookahead flag propagation
- `scripts/deep_backtest.py` - filtering and reporting paths that reject lookahead-tainted signal rows
- `docs/DATA_QUALITY_LESSONS.md` - durable record of why the pre-forward-indexer signal dataset was rejected

Important Phase 11 modules:

- `src/data/llm_news_processor.py` - local Ollama provider support and fallback handling
- `scripts/generate_signals.py` - `--ollama`, `--ollama-model`, and `--train-model` integration
- `src/models/trainer.py` - walk-forward LightGBM training, calibration, model persistence, and feature importance
- `scripts/train_model.py` - standalone training CLI for signal parquet files

Important Phase 12 modules:

- `scripts/deep_backtest.py` - relaxed diagnostic profile, risk override flags, and relaxed-mode report metadata
- `scripts/generate_report.py` - visible relaxed-mode warning in generated reports

Important Phase 13 modules:

- `src/strategies/liquidity_provider.py` - hardened liquidity harvester, adverse-selection blocking, tail-No filters, and PnL attribution
- `scripts/deep_backtest.py` - `liquidity-only` mode and dedicated liquidity harvester report generation
- `scripts/live_paper.py` - liquidity-only paper mode
- `src/execution/paper_trader.py` - paper-trading risk flags aligned with liquidity-only mode

Important Phase 14 modules and artifacts:

- `src/features/onchain_enhanced.py` - deterministic on-chain and market-flow feature proxies
- `src/features/fear_layer.py` - enhanced fear, temperature, regime, and interaction outputs
- `src/features/micro_round.py` - micro-round duration, spread, and maker-advantage features
- `src/features/feature_store.py` - enhanced feature-set integration
- `docs/FEATURE_ENGINEERING_IMPACT_REPORT.md` - documented ablation, feature importance, and updated verdict

---

## Installation

```bash
# Clone the repo
git clone https://github.com/YOURUSERNAME/pm-edge.git
cd pm-edge

# Create virtual environment
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

With `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

If macOS/Homebrew Python reports `externally-managed-environment`, create and activate a virtual environment first as shown above, or use `uv pip install`. Do not use `--break-system-packages` for this repo.

Copy environment variables:

```bash
cp .env.example .env
```

Then fill in your API keys.

---

## Usage

```bash
# Scan both venues for cross-venue opportunities
python -m scripts.scan --min-edge-bps 25

# Scan one venue
python -m scripts.scan --venue polymarket

# Submit a deterministic paper order
python -m scripts.paper_trade --market-id demo --outcome Yes --side buy --price 0.50 --size 2

# Run deterministic demo backtest
python -m scripts.backtest --no-save --edge-threshold 0.02 --stake 50

# Backtest a historical signal file
python -m scripts.backtest --strategy gbdt_v1 --period 2025-01-01:2026-05-01 --walk-forward --signals data/processed/signals.parquet

# Generate reusable historical signal partitions
python -m scripts.generate_signals --start-date 2025-03-01 --end-date 2025-05-01 --markets high-volume

# Backfill public Polymarket resolved markets and optional CLOB price history
python -m scripts.backfill_polymarket --tag crypto --resolved-only --fetch-history

# Generate signals with advanced feature groups using local Ollama
python -m scripts.generate_signals --start-date 2025-03-01 --end-date 2025-05-01 --use-llm --use-onchain --ollama-model qwen2.5:32b

# Run portfolio-level Kelly backtest
python -m scripts.backtest --portfolio --kelly-fraction 0.4 --max-exposure 0.2 --signals data/processed/signals.parquet

# Run one live paper cycle
python -m scripts.live_paper --once --interval 1800

# Run continuous paper trading with advanced features
python -m scripts.live_paper --interval 900 --kelly-fraction 0.35 --max-exposure 0.25 --review-threshold 0.08 --use-llm

# Open the monitoring dashboard
streamlit run src/monitoring/dashboard.py

# Run a deep base-vs-advanced portfolio backtest
python -m scripts.deep_backtest --period 2025-01-01:2026-05-01 --strategy gbdt_v1 --signals data/processed/signals --use-advanced-features --portfolio

# Run crypto-only deep backtest
python -m scripts.deep_backtest --period 2025-01-01:2026-05-01 --signals data/processed/signals --crypto-only --use-advanced-features --portfolio

# Run Phase 8 liquidity-first hybrid backtest with strict risk gates
python -m scripts.deep_backtest --period 2025-01-01:2026-05-01 --signals data/processed/signals --strategy hybrid_v1 --crypto-only --use-advanced-features --portfolio --mode hybrid --fear-layer-enabled --quarter-kelly --min-post-cost-edge 0.05

# Run dedicated liquidity / tail-insurance harvester mode
python -m scripts.deep_backtest --signals data/processed/signals_real_crypto_final.parquet --crypto-only --mode liquidity-only --quarter-kelly --kelly-fraction 0.25 --max-exposure 0.12

# Run live paper trading in liquidity-only mode
python -m scripts.live_paper --mode liquidity-only --interval 900 --kelly-fraction 0.25 --max-exposure 0.12

# Generate a Markdown report for the latest or specified deep backtest
python -m scripts.generate_report --input data/processed/deep_backtests

# Backtest liquidity providing
python -m scripts.liquidity_backtest --signals data/processed/signals --notify
```

Console scripts are also configured after installation:

```bash
pm-scan
pm-paper
pm-backtest
pm-trade
pm-edge
pm-generate-signals
pm-paper-trade
pm-deep-backtest
pm-generate-report
pm-liquidity-backtest
pm-train-model
pm-backfill-polymarket
```

Basic client/scanner usage:

```python
from decimal import Decimal

from core import MarketScanner, PredictionMarketClient, Venue


async def main() -> None:
    async with PredictionMarketClient() as client:
        scanner = MarketScanner(client, min_edge_bps=Decimal("25"))
        result = await scanner.scan_once([Venue.POLYMARKET, Venue.KALSHI])
        print(result.opportunities[:3])
```

Rank markets by Phase 1 edge score:

```bash
python -m scripts.edge --venue polymarket --limit 10
```

Configuration is loaded from `.env` using the `PM_EDGE_` prefix. Local development defaults to SQLite at `data/pm_edge.db`; set `PM_EDGE_DATABASE_URL` to a Postgres URL for deployed environments. Advanced LLM features are off unless enabled by CLI flag or `PM_EDGE_USE_ADVANCED_FEATURES=true`; cached prompt/response audit files are written under `PM_EDGE_LLM_CACHE_DIR`. LLM news processing defaults to local Ollama (`PM_EDGE_LLM_PROVIDER=ollama`, `PM_EDGE_OLLAMA_HOST=http://localhost:11434`, `PM_EDGE_OLLAMA_DEFAULT_MODEL=qwen2.5:32b`). Complex/high-value local calls can route to `PM_EDGE_OLLAMA_FALLBACK_MODEL=llama3.3:70b`; set `PM_EDGE_LLM_FALLBACK_PROVIDER=openai|claude|grok` and the matching API key for remote fallback if Ollama is unavailable.

Paper trading state defaults to `data/processed/live_paper/state.json` and audit decisions default to `data/processed/live_paper/audit.jsonl`. Review mode is on by default; for large edges, approve a decision by writing the market id or `approve_all` to `data/processed/live_paper/review_approval.txt`.

Phase 4 is intentionally paper-only. `pm-paper-trade` never sends orders to Polymarket or Kalshi; it reads markets, computes target paper positions, and writes the simulated decisions to local state/audit files.

Phase 8+ hybrid and liquidity-only modes remain research/paper-only. The allocator defaults preserve at least a 30% cash buffer, enforce a minimum 5-point post-fee/impact edge, use quarter Kelly when `--quarter-kelly` is set, and record Monte Carlo ruin diagnostics in each deep-backtest run folder. `--mode liquidity-only` disables directional betting and routes only maker-side liquidity / tail-insurance opportunities through fear-layer sizing, strict adverse-selection gates, and conservative quote accounting.

Telegram setup:

1. In Telegram, message `@BotFather`, create a bot, and copy the bot token.
2. Send a message to your bot, then get your chat id from Telegram bot updates or a trusted chat-id helper.
3. Set `PM_EDGE_TELEGRAM_ENABLED=true`, `PM_EDGE_TELEGRAM_BOT_TOKEN=...`, and `PM_EDGE_TELEGRAM_CHAT_ID=...` in `.env`.
4. Keep the token private; it can send messages as your bot. Do not commit `.env`.

---

## Development

- **Python 3.11+**
- Uses modern packaging (`pyproject.toml` + `hatchling`) and is uv-compatible
- Pre-commit-ready quality tooling
- Structured logging

Quality gates:

```bash
pytest
ruff check .
black --check .
ruff format --check .
mypy src scripts
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development workflow.

---

## Risk Warning

Trading prediction markets involves substantial risk of loss. This software is for **educational and research purposes**. Use at your own risk. Past performance (including backtests) is not indicative of future results.

---

## License

MIT License (see LICENSE file).
