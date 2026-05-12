# pm-edge

**A systematic prediction market trading system** for Polymarket, Kalshi, and related platforms.

Focused on finding and exploiting edge through information aggregation, cross-platform arbitrage, catalyst awareness, and disciplined risk management.

---

## Philosophy

- Edge comes from **speed + synthesis** of public information, not from secret signals.
- Robustness and risk control > raw predictive accuracy.
- Pre-registered rubrics, proper backtesting, and conservative sizing.
- Separate from all previous quant research (clean repo).

---

## Finalized Stack

- **Core runtime:** Python 3.11+, async-first architecture, `httpx`
- **Unified market access:** PMXT (`pmxt`) first, with Polymarket and Kalshi SDK fallbacks
- **Data and modeling:** pandas, numpy, scikit-learn, LightGBM
- **Persistence:** SQLModel with SQLite for local development and Postgres/Supabase-style deployments
- **Configuration:** Pydantic v2 + pydantic-settings + `.env`
- **Reliability:** tenacity retries, typed client boundaries, easy-to-mock adapters
- **Logging:** loguru + structlog with contextual structured logs
- **Tooling:** hatchling/uv-compatible packaging, black, ruff, mypy, pytest, pytest-asyncio, pre-commit

---

## Features (Planned / Completed)

### Phase 0 - Foundation

- [x] Project scaffold and packaging
- [x] Pydantic settings and `.env.example`
- [x] SQLModel market, price, resolution, position, and trade models
- [x] Async unified client foundation with PMXT-first fallback design
- [x] Structured logging setup
- [ ] Unified client integration tests against mocked PMXT / direct SDK adapters
- [ ] Real-time market scanner + arbitrage detector
- [ ] Historical resolved market database
- [ ] Paper trading engine with full logging

### Phase 1 - Core Edge Signals

- [ ] Poll aggregation engine
- [ ] News + sentiment velocity features
- [ ] Cross-market correlation models
- [ ] Simple probabilistic baseline models (Logistic / GBDT)

### Phase 2 - Advanced

- [ ] Catalyst calendar + pre-event positioning
- [ ] Kelly / fractional Kelly portfolio allocator
- [ ] Domain-specific models (elections, crypto events, macro, etc.)
- [ ] Live execution bot with risk limits

---

## Project Structure

```bash
pm-edge/
├── src/
│   ├── core/           # Market clients, unified interface
│   ├── data/           # Scrapers, poll aggregators, on-chain, news
│   ├── features/       # Feature engineering
│   ├── models/         # Probability models + baselines
│   ├── strategies/     # Arb, sentiment, catalyst strategies
│   ├── execution/      # Position sizing, risk, portfolio
│   ├── backtesting/    # Simulation and evaluation
│   └── utils/          # Config, logging, helpers
├── notebooks/          # Exploration and analysis
├── config/
├── data/               # .gitignore'd
├── scripts/            # CLI commands (scan, trade, backtest)
├── tests/
├── pyproject.toml
├── README.md
└── .env.example
```

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

Copy environment variables:

```bash
cp .env.example .env
```

Then fill in your API keys.

---

## Usage

```bash
# Scan for opportunities
python -m scripts.scan

# Run paper trading simulation
python -m scripts.paper_trade

# Backtest a strategy
python -m scripts.backtest --strategy sentiment_v1
```

Console scripts are also configured after installation:

```bash
pm-scan
pm-paper
pm-backtest
pm-trade
```

Basic client usage:

```python
from core import PredictionMarketClient, Venue


async def main() -> None:
    async with PredictionMarketClient() as client:
        markets = await client.fetch_markets([Venue.POLYMARKET, Venue.KALSHI])
        print(markets[:3])
```

Configuration is loaded from `.env` using the `PM_EDGE_` prefix. Local development defaults to SQLite at `data/pm_edge.db`; set `PM_EDGE_DATABASE_URL` to a Postgres URL for deployed environments.

---

## Development

- **Python 3.11+**
- Uses modern packaging (`pyproject.toml` + `hatchling`) and is uv-compatible
- Pre-commit-ready quality tooling
- Structured logging

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development workflow.

---

## Risk Warning

Trading prediction markets involves substantial risk of loss. This software is for **educational and research purposes**. Use at your own risk. Past performance (including backtests) is not indicative of future results.

---

## License

MIT License (see LICENSE file).
