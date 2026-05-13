# Feature Engineering Impact Report

Generated: 2026-05-13

## Scope

Phase 14 added an enhanced feature set for crypto prediction-market signals and evaluated it on the expanded 2025-YTD crypto backfill.

Inputs:

- Base signals: `data/processed/signals_crypto_2025_ytd_daily_hist.parquet`
- Enhanced trained signals: `data/processed/signals_crypto_2025_ytd_enhanced_trained.parquet`
- Liquidity-only run: `data/backtests/feature14_liquidity_20260513/20260513T172801Z_gbdt_v1`
- Hybrid run: `data/backtests/feature14_hybrid_20260513/20260513T172813Z_gbdt_v1`

## What Changed

New modules:

- `src/features/onchain_enhanced.py`
  - Whale-flow velocity
  - Smart-money cluster proxy
  - Funding-rate momentum and basis pressure
  - Open-interest surge and liquidation-cascade risk
  - TVL / volume delta proxies
  - Panic-reversion score

- `src/features/micro_round.py`
  - Duration-based micro-round detection
  - YES/NO sum excess
  - Incentive multiplier proxy
  - Maker-advantage score
  - Adverse-fill risk
  - 8-12c tail-zone marker

Updated modules:

- `src/features/fear_layer.py`
  - Multi-source fear snapshot fields
  - Fear x temperature interaction terms
  - Regime flags
  - Bounded market-temperature features

- `src/features/feature_store.py`
  - Optional enhanced feature extraction path

- `scripts/generate_signals.py`
  - Added `--feature-set enhanced`
  - Emits enhanced features into generated signal rows
  - Supports walk-forward model training over the enhanced feature matrix

## Signal Dataset Comparison

| Dataset | Rows | Markets | Date Range | Lookahead Rate | Mean Edge | 95th % Edge | Rows Edge >= 8% | 8-12c Tail Rows |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| Base daily historical | 47,932 | 1,575 | 2025-01-01 to 2026-04-01 | 12.69% | +0.2329 | +0.5245 | 35,930 | 3,877 |
| Enhanced trained | 47,932 | 1,575 | 2025-01-01 to 2026-04-01 | 12.69% | -0.1033 | +0.5140 | 8,109 | 3,877 |

The enhanced trained model materially reduced the number of high-edge rows versus the placeholder/base probability logic. That is directionally good for realism, but it also removed almost every row that could pass the hardened liquidity gates.

## Feature Importance

Top LightGBM importances from `models/gbdt_crypto_enhanced_v1.pkl.feature_importance.csv`:

| Feature | Importance |
|---|---:|
| `feature__spread` | 0.3210 |
| `feature__enh_onchain_asset_beta` | 0.1046 |
| `duration_minutes` | 0.1046 |
| `feature__micro_maker_advantage_score` | 0.0908 |
| `feature__enh_volume_liquidity_ratio` | 0.0637 |
| `feature__enh_whale_flow_velocity` | 0.0585 |
| `market_probability` | 0.0568 |
| `feature__enh_smart_money_cluster_score` | 0.0525 |
| `feature__micro_duration_decay` | 0.0331 |
| `feature__enh_basis_pressure` | 0.0241 |

Interpretation:

- The model used the new feature families, especially spread, asset class, duration, maker advantage, volume/liquidity, and whale-flow proxies.
- True exogenous on-chain fields are still sparse, so several enhanced fields are deterministic proxies rather than live chain data.
- Fear-regime features had zero importance in this run because default historical fear snapshots were static. They need real historical fear series before they can prove value.

## Micro-Round Activation

Enhanced signal diagnostics:

- `micro_is_5_15m`: 0 rows
- `micro_sum_excess > 0.02`: 0 rows
- `micro_tail_zone_8_12c`: 3,877 rows

The current historical dataset does not contain usable 5-15 minute micro-round structure or reliable both-sides price sums above 1.02. Micro-round quoting cannot be validated on this data as currently backfilled.

## Backtest Results

### Liquidity-Only, Enhanced

Run: `data/backtests/feature14_liquidity_20260513/20260513T172801Z_gbdt_v1`

| Metric | Value |
|---|---:|
| Quotes / bets | 0 |
| Net PnL | 0.00 |
| Sharpe | 0.00 |
| Max drawdown | 0.00 |
| Monte Carlo ruin probability | 0.00 |
| Rejected rows | 41,851 |
| Rejected adverse selection | 5,182 |
| Rejected insufficient liquidity | 20,451 |
| Rejected spread too tight | 16,197 |

### Hybrid, Enhanced

Run: `data/backtests/feature14_hybrid_20260513/20260513T172813Z_gbdt_v1`

| Metric | Value |
|---|---:|
| Trades | 0 |
| Hybrid net PnL | 0.00 |
| Liquidity PnL | 0.00 |
| Portfolio Sharpe | 0.00 |
| Rejected by liquidity cap | 17,027 |
| Rejected by edge | 9,338 |
| Rejected by post-cost edge | 15,486 |

## Verdict

No-Go.

The enhanced feature sprint improved the engineering substrate and made the model more realistic, but it did not unlock a tradable liquidity edge on the expanded 2025-YTD crypto backfill under the hardened rules. The main blockers are:

- The trained model removes many placeholder high-edge rows.
- Strict liquidity gates reject all surviving candidates.
- Historical micro-round data is insufficient for both-sides quoting validation.
- Fear features are not yet backed by real historical fear inputs.

## Recommendations

1. Keep the enhanced feature modules. They are useful, typed, tested, and the trained model uses several of them.
2. Do not loosen production liquidity gates just to force trades. The current zero-trade result is more honest than accepting weak fills.
3. Prioritize data quality over new model complexity:
   - Backfill real bid/ask depth, spread, and both-side token books for micro-round markets.
   - Add real historical crypto fear/greed, VIX, funding, OI, liquidation, and whale-flow time series.
   - Tag market duration and event type at ingestion time, not as a downstream guess.
4. Re-run liquidity validation only after the dataset can actually represent maker opportunities.
5. Keep hybrid disabled for now. The enhanced run did not create a reliable directional or liquidity signal.
