# pm-edge

**A systematic prediction market trading system** for Polymarket, Kalshi, and related platforms.

Focused on finding and exploiting edge through information aggregation, cross-platform arbitrage, catalyst awareness, and disciplined risk management.

---

## Status

Phase 0 is complete. The repo now has a typed async client boundary, mocked backend tests, a scanner/arbitrage detector, local market-history persistence, and an in-memory paper trading engine. Strategy-specific edge logic starts in Phase 1.

Current verified commit line:

- `3531cef` - bootstrap project foundation
- `2f698a3` - finish Phase 0 foundation

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
- [x] Unified client integration tests against mocked PMXT / direct SDK adapters
- [x] Real-time market scanner + arbitrage detector
- [x] Historical resolved market database
- [x] Paper trading engine with full logging

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
│   ├── core/           # Config, unified client, scanner, arbitrage detection
│   ├── data/           # Persistence, scrapers, poll aggregators, on-chain, news
│   ├── features/       # Feature engineering
│   ├── models/         # Probability models + baselines
│   ├── strategies/     # Arb, sentiment, catalyst strategy modules
│   ├── execution/      # Paper trading, position sizing, risk, portfolio
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
```

Console scripts are also configured after installation:

```bash
pm-scan
pm-paper
pm-backtest
pm-trade
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

Configuration is loaded from `.env` using the `PM_EDGE_` prefix. Local development defaults to SQLite at `data/pm_edge.db`; set `PM_EDGE_DATABASE_URL` to a Postgres URL for deployed environments.

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
