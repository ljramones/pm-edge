# Repository Exploration Report

Generated: 2026-05-13 14:08:08

Constraints followed: local filesystem inspection only; no network calls; no source files modified; secret-like config values redacted where encountered.

## 1. Data Directory Inventory

| Path | Size | Extension | Last Modified | Parquet Rows | Parquet Columns | Approx Uncompressed |
| --- | --- | --- | --- | --- | --- | --- |
| data/.DS_Store | 6.0 KB | (none) | 2026-05-12 21:56:42 |  |  |  |
| data/.gitkeep | 1 B | (none) | 2026-05-11 21:51:19 |  |  |  |
| data/backtests/.DS_Store | 6.0 KB | (none) | 2026-05-13 08:33:18 |  |  |  |
| data/backtests/diagnostic_directional_20260512/.DS_Store | 6.0 KB | (none) | 2026-05-13 08:33:18 |  |  |  |
| data/backtests/phase_13_7_liquidity_validation_report.md | 4.6 KB | .md | 2026-05-13 13:02:52 |  |  |  |
| data/processed/.gitkeep | 1 B | (none) | 2026-05-11 21:22:49 |  |  |  |
| data/processed/live_paper/audit.jsonl | 194 B | .jsonl | 2026-05-12 09:52:25 |  |  |  |
| data/processed/live_paper/state.json | 635 B | .json | 2026-05-12 09:52:25 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-02e6f8cda1-4f53cda18c.json | 3.4 KB | .json | 2026-05-13 10:55:52 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-050484c814-4f53cda18c.json | 3.2 KB | .json | 2026-05-13 10:55:47 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-1529c70597-4f53cda18c.json | 2.4 KB | .json | 2026-05-13 10:55:41 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-179aaf51a2-4f53cda18c.json | 1.4 KB | .json | 2026-05-13 10:56:10 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-2021a5d17e-4f53cda18c.json | 1.5 KB | .json | 2026-05-13 10:55:55 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-48ac1b01e1-4f53cda18c.json | 1.5 KB | .json | 2026-05-13 10:56:13 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-622d365c0a-4f53cda18c.json | 1.5 KB | .json | 2026-05-13 10:55:58 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-86a014f9b6-4f53cda18c.json | 1.5 KB | .json | 2026-05-13 10:55:37 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-9e042ab83d-4f53cda18c.json | 1.5 KB | .json | 2026-05-13 10:56:06 |  |  |  |
| data/processed/llm_cache/-ollama-llama3.2-b510413bd6-4f53cda18c.json | 1.7 KB | .json | 2026-05-13 10:56:02 |  |  |  |
| data/processed/llm_cache/-ollama-qwen2.5-32b-a5bea0af25-4f53cda18c.json | 1.5 KB | .json | 2026-05-13 10:53:43 |  |  |  |
| data/processed/llm_cache/106209470905140133419252056944399671970425852277950125119183011062762795065913-ollama-qwen2.5-32b-1d98185a20-4f53cda18c.json | 1.9 KB | .json | 2026-05-13 11:12:39 |  |  |  |
| data/processed/llm_cache/109330882058614292316023690415034941592701651157216579359290853708015909209656-ollama-qwen2.5-32b-e2194ef756-4f53cda18c.json | 2.0 KB | .json | 2026-05-13 11:12:30 |  |  |  |
| data/processed/llm_cache/110251828161543119357013227499774714771527179764174739487025581227481937033858-ollama-qwen2.5-32b-dde74f44c0-4f53cda18c.json | 2.1 KB | .json | 2026-05-13 11:12:49 |  |  |  |
| data/processed/llm_cache/111128191581505463501777127559667396812474366956707382672202929745167742497287-ollama-qwen2.5-32b-5fe96276cc-4f53cda18c.json | 2.3 KB | .json | 2026-05-13 11:12:59 |  |  |  |
| data/processed/llm_cache/12431602778270498619957996348061794666136770386023570384429499899348597994426-ollama-qwen2.5-32b-d27ed83b97-4f53cda18c.json | 2.2 KB | .json | 2026-05-13 11:11:40 |  |  |  |
| data/processed/llm_cache/19653256042621618513359712634441094602989715483047297038180875646470350509987-ollama-qwen2.5-32b-88808d80dd-4f53cda18c.json | 2.1 KB | .json | 2026-05-13 11:12:00 |  |  |  |
| data/processed/llm_cache/40857835778606083269545737690918842295223704526175143893728294436131619750624-ollama-qwen2.5-32b-db70cfeb9a-4f53cda18c.json | 2.8 KB | .json | 2026-05-13 11:13:21 |  |  |  |
| data/processed/llm_cache/423159642859616304693748948006533503426876027949474243126283164948112081583-ollama-qwen2.5-32b-53ef495c0f-4f53cda18c.json | 2.2 KB | .json | 2026-05-13 11:12:22 |  |  |  |
| data/processed/llm_cache/44277901818108806761236452190579702355420207259376614876965091268791774916719-ollama-qwen2.5-32b-7382d91c43-4f53cda18c.json | 2.0 KB | .json | 2026-05-13 11:13:09 |  |  |  |
| data/processed/llm_cache/4948120852309116508091614170839376668966884700948989771484997808380844459394-ollama-qwen2.5-32b-e73fa7c170-4f53cda18c.json | 2.8 KB | .json | 2026-05-13 11:12:12 |  |  |  |
| data/processed/llm_cache/60105229286427884692660113868141858131134689149752564702347657042086215753173-ollama-qwen2.5-32b-935c46c961-4f53cda18c.json | 2.4 KB | .json | 2026-05-13 11:11:28 |  |  |  |
| data/processed/llm_cache/65369389559359751092648075783441381774936099007147163772313101980124460556437-ollama-qwen2.5-32b-6ba25a6b16-4f53cda18c.json | 2.1 KB | .json | 2026-05-13 11:11:50 |  |  |  |
| data/processed/llm_cache/78335109906317895545656625449434377727121794317480975251903274107376332097404-ollama-qwen2.5-32b-833a4e6f2d-4f53cda18c.json | 2.5 KB | .json | 2026-05-13 11:13:31 |  |  |  |
| data/processed/llm_cache/85050326633307103921116183405959204984545408066775745936128241765963012426383-ollama-qwen2.5-32b-1e476313c5-4f53cda18c.json | 2.0 KB | .json | 2026-05-13 11:11:13 |  |  |  |
| data/processed/llm_cache/89855632938622748749936219831384139658987159510868142817621934894829168855877-ollama-qwen2.5-32b-3aa6a57b8f-4f53cda18c.json | 2.5 KB | .json | 2026-05-13 11:13:41 |  |  |  |
| data/processed/llm_cache/98781440823957607611119310151867652433846300646102154027323388160906374652595-ollama-qwen2.5-32b-a512e0ff97-4f53cda18c.json | 2.8 KB | .json | 2026-05-13 11:13:52 |  |  |  |
| data/processed/polymarket_price_history.parquet | 9.8 MB | .parquet | 2026-05-13 12:54:31 | 4011631 | 6 | 11.7 MB |
| data/processed/resolved_markets.parquet | 1.1 MB | .parquet | 2026-05-13 12:51:10 | 3000 | 36 | 1.9 MB |
| data/processed/signals_crypto_2025_ytd_daily_hist.parquet | 513.7 KB | .parquet | 2026-05-13 12:59:30 | 47932 | 36 | 1008.3 KB |
| data/processed/signals_crypto_2025_ytd_enhanced_trained.parquet | 2.7 MB | .parquet | 2026-05-13 13:27:43 | 47932 | 83 | 3.9 MB |
| data/processed/signals_real_crypto_final.parquet | 133.8 KB | .parquet | 2026-05-13 11:27:37 | 20315 | 38 | 246.5 KB |
| data/processed/signals_real_crypto_historical.parquet | 22.0 KB | .parquet | 2026-05-12 22:10:08 | 16 | 38 | 5.9 KB |
| data/processed/signals_real_crypto_large.parquet | 59.9 KB | .parquet | 2026-05-13 07:07:55 | 20315 | 38 | 169.5 KB |
| data/processed/signals_real_crypto_large_hist.parquet | 133.8 KB | .parquet | 2026-05-13 07:13:58 | 20315 | 38 | 246.5 KB |
| data/processed/signals_real_crypto_v3.parquet | 50.7 KB | .parquet | 2026-05-12 21:04:44 | 19749 | 34 | 157.7 KB |
| data/processed/signals_real_trained.parquet | 156.2 KB | .parquet | 2026-05-13 11:50:01 | 20315 | 39 | 272.5 KB |
| data/raw/.gitkeep | 1 B | (none) | 2026-05-11 21:22:49 |  |  |  |

## 2. Signal Schema

Chosen main signals file: `data/processed/signals_crypto_2025_ytd_enhanced_trained.parquet`. It was selected as the largest signal parquet candidate by row count, with file size as tie-breaker.

- Total rows: 47,932
- Total columns: 30

Timestamp/date ranges:
| Column | Min | Max | Non-null Parsed |
| --- | --- | --- | --- |
| resolved_at | 2025-01-01 01:55:59+00:00 | 2026-04-01 08:14:21+00:00 | 47932 |
| as_of | 2025-01-01 00:00:00+00:00 | 2026-04-01 00:00:00+00:00 | 47932 |

Full column list and dtypes:
| Column | Dtype |
| --- | --- |
| market_id | str |
| question | str |
| condition_id | str |
| slug | str |
| outcome | int64 |
| resolved_at | datetime64[us, UTC] |
| as_of | datetime64[us, UTC] |
| venue | str |
| market_probability | float64 |
| model_probability | float64 |
| edge | float64 |
| confidence | float64 |
| features | object |
| reasoning | str |
| category | str |
| liquidity | float64 |
| volume | float64 |
| fear_sizing_multiplier | float64 |
| advanced_enabled | bool |
| price_source | str |
| is_lookahead | bool |
| historical_price_at | datetime64[us, UTC] |
| historical_price_age_seconds | float64 |
| liquidity_source | str |
| duration_minutes | float64 |
| yes_no_sum | float64 |
| feature_set | str |
| base_model_probability | float64 |
| advanced_model_probability | float64 |
| trained_model_probability | float64 |

Top 10 columns by null count:
| Column | Null Count |
| --- | --- |
| yes_no_sum | 6081 |
| historical_price_age_seconds | 6081 |
| historical_price_at | 6081 |
| trained_model_probability | 4985 |
| question | 0 |
| advanced_model_probability | 0 |
| base_model_probability | 0 |
| feature_set | 0 |
| duration_minutes | 0 |
| liquidity_source | 0 |

Two example rows, with long string/nested values truncated:
| market_id | question | condition_id | slug | outcome | resolved_at | as_of | venue | market_probability | model_probability | edge | confidence | features | reasoning | category | liquidity | volume | fear_sizing_multiplier | advanced_enabled | price_source | is_lookahead | historical_price_at | historical_price_age_seconds | liquidity_source | duration_minutes | yes_no_sum | feature_set | base_model_probability | advanced_model_probability | trained_model_probability |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 253258 | OpenSea token >1 billion a week after launch? | 0x0bc614c4fc8a19f63c46fd7f5b270704c3286f0e436e8b02591166f220544e14 | opensea-token-1-billion-a-week-after-launch | 1 | 2025-01-01 09:42:02+00:00 | 2025-01-01 00:00:00+00:00 | polymarket | 0.505 | 0.5 | -0.0050000000000000044 | 0.050000000000000044 | {"attention_decay": null, "cross_source_agreement": 0.5, "duration_minutes": ... | resolved-market backfill bootstrap signal | crypto | 0.0 | 2444775.94761701 | 1.0 | True | clob_history_yes | False | 2024-12-31 23:00:04+00:00 | 3596.0 | resolved_market_snapshot | 570616.6386333334 | 1.0 | enhanced | 0.5 | 0.5 |  |
| 253260 | OpenSea token announcement in 2024? | 0xf5696d8eb7ee5bb4fdd58465f502c8962c8972a4de4d64077662b41e658d2401 | opensea-token-in-2024 | 0 | 2025-01-01 08:08:04+00:00 | 2025-01-01 00:00:00+00:00 | polymarket | 0.012 | 0.5 | 0.488 | 1.0 | {"attention_decay": null, "cross_source_agreement": 0.5, "duration_minutes": ... | resolved-market backfill bootstrap signal | crypto | 0.0 | 338289.914265 | 1.0 | True | clob_history_yes | False | 2024-12-31 23:00:04+00:00 | 3596.0 | resolved_market_snapshot | 570467.0914333333 | 1.0 | enhanced | 0.5 | 0.5 |  |

Nested dictionary columns:
- `features` keys: `attention_decay`, `cross_source_agreement`, `duration_minutes`, `effective_attention`, `enh_address_cluster_activity`, `enh_basis_pressure`, `enh_funding_rate_momentum`, `enh_hours_to_resolution`, `enh_is_final_day`, `enh_is_weekend`, `enh_lifecycle_progress`, `enh_liquidation_cascade_risk`, `enh_market_age_hours`, `enh_onchain_asset_beta`, `enh_open_interest_surge`, `enh_panic_reversion_score`, `enh_smart_money_cluster_score`, `enh_tvl_delta`, `enh_volume_delta`, `enh_volume_liquidity_ratio`, `enh_whale_flow_velocity`, `fear_attention_interaction`, `fear_regime_liquidity_stress`, `fear_route`, `fear_score`, `fear_sizing_multiplier`, `fear_temperature_interaction`, `high_fear_regime`, `high_temperature_regime`, `llm_news_momentum`, `llm_news_score`, `llm_probability`, `llm_uncertainty`, `market_temperature`, `mention_count_7d`, `micro_adverse_fill_risk`, `micro_depth_proxy`, `micro_duration_decay`, `micro_duration_minutes`, `micro_incentive_multiplier`, `micro_is_5_15m`, `micro_is_subhour`, `micro_maker_advantage_score`, `micro_sum_excess`, `micro_tail_zone_8_12c`, `micro_yes_no_sum`, `onchain_funding_rate`, `onchain_tvl_change_24h`, `onchain_volume_surge`, `onchain_whale_activity`, `spread`, `top_book_liquidity`, `volume_attention_proxy`, `yes_no_sum`

Other signal candidates considered:
| Path | Rows | Size |
| --- | --- | --- |
| data/processed/signals_crypto_2025_ytd_enhanced_trained.parquet | 47,932 | 2.7 MB |
| data/processed/signals_crypto_2025_ytd_daily_hist.parquet | 47,932 | 513.7 KB |
| data/processed/signals_real_trained.parquet | 20,315 | 156.2 KB |
| data/processed/signals_real_crypto_final.parquet | 20,315 | 133.8 KB |
| data/processed/signals_real_crypto_large_hist.parquet | 20,315 | 133.8 KB |
| data/processed/signals_real_crypto_large.parquet | 20,315 | 59.9 KB |
| data/processed/signals_real_crypto_v3.parquet | 19,749 | 50.7 KB |
| data/processed/signals_real_crypto_historical.parquet | 16 | 22.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2024-03-23/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2024-07-13/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2023-10-26/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2023-08-12/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2023-10-19/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2023-10-21/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2024-07-14/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2024-03-24/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2023-08-15/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2023-10-17/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2024-07-22/signals.parquet | 0 | 8.0 KB |
| data/processed/signals_real_crypto_fixed.parquet/date=2024-03-12/signals.parquet | 0 | 8.0 KB |


## 3. Backfill Script

`scripts/backfill_polymarket.py` exists. Full contents:

```python
"""Backfill public Polymarket market metadata and optional CLOB price history."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pandas as pd
from loguru import logger
from tqdm import tqdm

from utils import resolve_repo_path

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"
RAW_DIR = resolve_repo_path(Path("data/raw/polymarket"))
PROCESSED_DIR = resolve_repo_path(Path("data/processed"))
RESOLVED_PARQUET = PROCESSED_DIR / "resolved_markets.parquet"
PRICE_HISTORY_PARQUET = PROCESSED_DIR / "polymarket_price_history.parquet"


@dataclass(frozen=True)
class BackfillConfig:
    """Runtime configuration for the Polymarket public backfill."""

    tag: str | None
    resolved_only: bool
    limit: int
    fetch_history: bool
    raw_dir: Path = RAW_DIR
    processed_dir: Path = PROCESSED_DIR
    page_size: int = 500
    request_delay: float = 0.25
    timeout_seconds: float = 30.0
    history_interval: str = "1d"
    history_fidelity: int = 60
    history_chunk_days: int = 14
    overwrite: bool = False


class PolymarketBackfiller:
    """Async public Polymarket backfill client with local raw-cache persistence."""

    def __init__(self, config: BackfillConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self.client = client or httpx.AsyncClient(timeout=config.timeout_seconds)
        self._owns_client = client is None

    async def close(self) -> None:
        """Close the owned HTTP client."""

        if self._owns_client:
            await self.client.aclose()

    async def run(self) -> pd.DataFrame:
        """Fetch requested markets, save raw JSON, and write resolved-market parquet."""

        ensure_dirs(self.config.raw_dir, self.config.processed_dir)
        tag_id = await self.resolve_tag_id(self.config.tag) if self.config.tag else None
        markets: list[dict[str, Any]] = []
        scopes = (
            [("resolved", True)]
            if self.config.resolved_only
            else [("active", False), ("resolved", True)]
        )
        for scope, closed in scopes:
            logger.info(
                "polymarket_scope_fetch_started", scope=scope, tag=self.config.tag, tag_id=tag_id
            )
            fetched = await self.fetch_markets(closed=closed, tag_id=tag_id, scope=scope)
            logger.info("polymarket_scope_fetch_finished", scope=scope, count=len(fetched))
            markets.extend(fetched)

        unique_markets = dedupe_markets(markets)
        resolved_markets = [market for market in unique_markets if is_resolved_market(market)]
        resolved_frame = markets_to_resolved_frame(resolved_markets)
        resolved_path = self.config.processed_dir / RESOLVED_PARQUET.name
        resolved_frame.to_parquet(resolved_path, index=False)
        logger.info(
            "polymarket_resolved_parquet_written", path=str(resolved_path), rows=len(resolved_frame)
        )

        if self.config.fetch_history and resolved_markets:
            await self.fetch_price_histories(resolved_markets)
            history_frame = price_history_frame_from_raw(self.config.raw_dir)
            history_path_out = self.config.processed_dir / PRICE_HISTORY_PARQUET.name
            history_frame.to_parquet(history_path_out, index=False)
            logger.info(
                "polymarket_price_history_parquet_written",
                path=str(history_path_out),
                rows=len(history_frame),
            )
        return resolved_frame

    async def resolve_tag_id(self, tag: str | None) -> int | None:
        """Resolve a tag slug/id to the Gamma tag id used by market filtering."""

        if tag is None:
            return None
        if tag.isdigit():
            return int(tag)
        payload = await self.request_json(
            f"{GAMMA_BASE_URL}/tags/slug/{tag_slug(tag)}",
            params={"include_template": "false"},
        )
        if isinstance(payload, dict) and payload.get("id") is not None:
            return int(cast(str | int, payload["id"]))
        raise RuntimeError(f"Unable to resolve Polymarket tag slug: {tag}")

    async def fetch_markets(
        self, *, closed: bool, tag_id: int | None, scope: str
    ) -> list[dict[str, Any]]:
        """Fetch markets through Gamma keyset pagination."""

        markets: list[dict[str, Any]] = []
        cursor: str | None = None
        progress_total = self.config.limit if self.config.limit > 0 else None
        with tqdm(total=progress_total, desc=f"polymarket:{scope}") as progress:
            while self.config.limit <= 0 or len(markets) < self.config.limit:
                page_limit = self.config.page_size
                if self.config.limit > 0:
                    page_limit = min(page_limit, self.config.limit - len(markets))
                params: list[tuple[str, str]] = [
                    ("closed", str(closed).lower()),
                    ("include_tag", "true"),
                    ("limit", str(page_limit)),
                    ("order", "volume_num"),
                    ("ascending", "false"),
                ]
                if cursor:
                    params.append(("after_cursor", cursor))
                if tag_id is not None:
                    params.append(("tag_id", str(tag_id)))
                    params.append(("related_tags", "true"))
                payload = await self.request_json(f"{GAMMA_BASE_URL}/markets/keyset", params=params)
                page_markets, cursor = parse_markets_page(payload)
                if not page_markets:
                    break
                for market in page_markets:
                    tagged_market = dict(market)
                    tagged_market["_pm_edge_backfill_scope"] = scope
                    tagged_market["_pm_edge_fetched_at"] = utc_now_iso()
                    if self.write_raw_market(tagged_market, scope=scope):
                        logger.debug(
                            "polymarket_market_raw_written", market_id=market_identifier(market)
                        )
                    markets.append(tagged_market)
                    progress.update(1)
                    if 0 < self.config.limit <= len(markets):
                        break
                if not cursor:
                    break
                await asyncio.sleep(self.config.request_delay)
        return markets

    async def fetch_price_histories(self, markets: list[dict[str, Any]]) -> None:
        """Fetch CLOB price history for resolved markets with CLOB token IDs."""

        tasks = [
            (market, token_id, outcome)
            for market in markets
            for token_id, outcome in clob_tokens_with_outcomes(market)
        ]
        with tqdm(total=len(tasks), desc="polymarket:history") as progress:
            for market, token_id, outcome in tasks:
                market_id = market_identifier(market)
                path = history_path(
                    self.config.raw_dir,
                    market_id=market_id,
                    token_id=token_id,
                    interval=self.config.history_interval,
                )
                if path.exists() and not self.config.overwrite:
                    progress.update(1)
                    continue
                params = {
                    "market": token_id,
                    "interval": self.config.history_interval,
                    "fidelity": str(self.config.history_fidelity),
                }
                start_ts = unix_seconds(
                    market.get("startDate") or market.get("startDateIso") or market.get("createdAt")
                )
                end_ts = unix_seconds(
                    market.get("closedTime") or market.get("endDate") or market.get("endDateIso")
                )
                if start_ts is not None:
                    params["startTs"] = str(start_ts)
                if end_ts is not None:
                    params["endTs"] = str(end_ts)
                try:
                    payload = await self.fetch_price_history_payload(
                        token_id=token_id,
                        params=params,
                        start_ts=start_ts,
                        end_ts=end_ts,
                    )
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "polymarket_history_fetch_failed",
                        market_id=market_id,
                        token_id=token_id,
                        status_code=exc.response.status_code,
                    )
                    progress.update(1)
                    continue
                write_json(
                    path,
                    {
                        "fetched_at": utc_now_iso(),
                        "source": f"{CLOB_BASE_URL}/prices-history",
                        "params": params,
                        "market_id": market_id,
                        "token_id": token_id,
                        "outcome": outcome,
                        "payload": payload,
                    },
                )
                await asyncio.sleep(self.config.request_delay)
                progress.update(1)

    async def fetch_price_history_payload(
        self,
        *,
        token_id: str,
        params: dict[str, str],
        start_ts: int | None,
        end_ts: int | None,
    ) -> dict[str, Any]:
        """Fetch CLOB price history, chunking long bounded requests when needed."""

        if start_ts is None or end_ts is None:
            return cast(
                dict[str, Any],
                await self.request_json(f"{CLOB_BASE_URL}/prices-history", params=params),
            )
        max_window = self.config.history_chunk_days * 86_400
        if end_ts - start_ts <= max_window:
            return cast(
                dict[str, Any],
                await self.request_json(f"{CLOB_BASE_URL}/prices-history", params=params),
            )
        history: list[dict[str, Any]] = []
        cursor = start_ts
        while cursor < end_ts:
            chunk_end = min(cursor + max_window, end_ts)
            chunk_params = dict(params)
            chunk_params["startTs"] = str(cursor)
            chunk_params["endTs"] = str(chunk_end)
            try:
                payload = await self.request_json(
                    f"{CLOB_BASE_URL}/prices-history", params=chunk_params
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "polymarket_history_chunk_failed",
                    token_id=token_id,
                    start_ts=cursor,
                    end_ts=chunk_end,
                    status_code=exc.response.status_code,
                )
                cursor = chunk_end
                continue
            chunk_history = payload.get("history") if isinstance(payload, dict) else []
            if isinstance(chunk_history, list):
                history.extend([item for item in chunk_history if isinstance(item, dict)])
            cursor = chunk_end
            await asyncio.sleep(self.config.request_delay)
        deduped = {
            str(item.get("t") or item.get("timestamp") or item.get("time")): item
            for item in history
        }
        return {"history": list(deduped.values())}

    async def request_json(
        self, url: str, *, params: dict[str, str] | list[tuple[str, str]] | None = None
    ) -> Any:
        """GET JSON with simple retry/backoff and respectful delay."""

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self.client.get(url, params=cast(Any, params))
                response.raise_for_status()
                await asyncio.sleep(self.config.request_delay)
                return response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_error = exc
                sleep_for = self.config.request_delay * (2**attempt)
                logger.warning(
                    "polymarket_request_failed",
                    url=url,
                    attempt=attempt + 1,
                    error=str(exc),
                    sleep_seconds=sleep_for,
                )
                await asyncio.sleep(sleep_for)
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Request failed without error: {url}")

    def write_raw_market(self, market: dict[str, Any], *, scope: str) -> bool:
        """Write one market raw cache file. Returns True when a file was written."""

        market_id = market_identifier(market)
        path = market_path(self.config.raw_dir, market_id=market_id, scope=scope)
        if path.exists() and not self.config.overwrite:
            return False
        write_json(
            path,
            {
                "fetched_at": utc_now_iso(),
                "source": f"{GAMMA_BASE_URL}/markets/keyset",
                "scope": scope,
                "market_id": market_id,
                "payload": market,
            },
        )
        return True


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""

    parser = argparse.ArgumentParser(description="Backfill public Polymarket markets.")
    parser.add_argument("--tag", help='Optional tag slug/id filter, e.g. "crypto".')
    parser.add_argument(
        "--resolved-only", action="store_true", help="Fetch only closed/resolved markets."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum markets per scope. Use 0 for no explicit cap.",
    )
    parser.add_argument(
        "--fetch-history",
        action="store_true",
        help="Fetch CLOB price history for resolved-market token IDs.",
    )
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument(
        "--history-interval", default="1d", choices=["max", "all", "1m", "1w", "1d", "6h", "1h"]
    )
    parser.add_argument("--history-fidelity", type=int, default=60)
    parser.add_argument("--history-chunk-days", type=int, default=14)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


async def run() -> int:
    """CLI runner."""

    args = parse_args()
    config = BackfillConfig(
        tag=args.tag,
        resolved_only=args.resolved_only,
        limit=args.limit,
        fetch_history=args.fetch_history,
        raw_dir=resolve_repo_path(args.raw_dir),
        processed_dir=resolve_repo_path(args.processed_dir),
        page_size=args.page_size,
        request_delay=args.request_delay,
        history_interval=args.history_interval,
        history_fidelity=args.history_fidelity,
        history_chunk_days=args.history_chunk_days,
        overwrite=args.overwrite,
    )
    backfiller = PolymarketBackfiller(config)
    try:
        resolved = await backfiller.run()
    finally:
        await backfiller.close()
    print(
        "Polymarket backfill complete: "
        f"resolved_rows={len(resolved)} parquet={config.processed_dir / RESOLVED_PARQUET.name}"
    )
    return 0


def main() -> None:
    """Console entrypoint."""

    raise SystemExit(asyncio.run(run()))


def ensure_dirs(raw_dir: Path, processed_dir: Path) -> None:
    """Create raw and processed output directories."""

    (raw_dir / "markets").mkdir(parents=True, exist_ok=True)
    (raw_dir / "history").mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)


def parse_markets_page(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Parse Gamma keyset or legacy markets responses."""

    if isinstance(payload, dict):
        raw_markets = payload.get("markets", [])
        cursor = payload.get("next_cursor")
    elif isinstance(payload, list):
        raw_markets = payload
        cursor = None
    else:
        raw_markets = []
        cursor = None
    markets = [item for item in raw_markets if isinstance(item, dict)]
    return cast(list[dict[str, Any]], markets), str(cursor) if cursor else None


def markets_to_resolved_frame(markets: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert raw resolved Gamma market JSON into a clean DataFrame."""

    rows = [resolved_market_row(market) for market in markets]
    return pd.DataFrame(rows)


def resolved_market_row(market: dict[str, Any]) -> dict[str, Any]:
    """Flatten one Gamma market object into stable resolved-market columns."""

    outcomes = parse_jsonish_list(market.get("outcomes"))
    outcome_prices = [
        parse_float(value) for value in parse_jsonish_list(market.get("outcomePrices"))
    ]
    token_ids = [str(value) for value in parse_jsonish_list(market.get("clobTokenIds"))]
    events = market.get("events") if isinstance(market.get("events"), list) else []
    first_event = events[0] if events and isinstance(events[0], dict) else {}
    tags = extract_tag_slugs(market)
    winning_outcome, winning_price = infer_winning_outcome(outcomes, outcome_prices)
    return {
        "market_id": market_identifier(market),
        "condition_id": market.get("conditionId"),
        "question_id": market.get("questionID") or market.get("questionId"),
        "slug": market.get("slug"),
        "question": market.get("question"),
        "category": market.get("category") or first_event.get("category"),
        "tags": tags,
        "event_id": first_event.get("id"),
        "event_slug": first_event.get("slug"),
        "event_title": first_event.get("title"),
        "active": market.get("active"),
        "closed": market.get("closed"),
        "archived": market.get("archived"),
        "enable_order_book": market.get("enableOrderBook"),
        "start_date": market.get("startDate") or market.get("startDateIso"),
        "end_date": market.get("endDate") or market.get("endDateIso"),
        "closed_time": market.get("closedTime"),
        "created_at": market.get("createdAt"),
        "updated_at": market.get("updatedAt"),
        "resolved_by": market.get("resolvedBy"),
        "uma_resolution_status": market.get("umaResolutionStatus"),
        "volume": parse_float(market.get("volume")),
        "liquidity": parse_float(market.get("liquidity")),
        "volume_num": parse_float(market.get("volumeNum")),
        "liquidity_num": parse_float(market.get("liquidityNum")),
        "outcomes": outcomes,
        "outcome_prices": outcome_prices,
        "clob_token_ids": token_ids,
        "winning_outcome": winning_outcome,
        "winning_price": winning_price,
        "yes_price": outcome_price_for(outcomes, outcome_prices, "Yes"),
        "no_price": outcome_price_for(outcomes, outcome_prices, "No"),
        "best_bid": parse_float(market.get("bestBid")),
        "best_ask": parse_float(market.get("bestAsk")),
        "last_trade_price": parse_float(market.get("lastTradePrice")),
        "raw_downloaded_at": market.get("_pm_edge_fetched_at"),
    }


def is_resolved_market(market: dict[str, Any]) -> bool:
    """Return whether a market should be treated as resolved/closed for backfill purposes."""

    if bool(market.get("closed")):
        return True
    status = str(market.get("umaResolutionStatus") or "").lower()
    return status in {"resolved", "settled"}


def clob_tokens_with_outcomes(market: dict[str, Any]) -> list[tuple[str, str | None]]:
    """Return CLOB token ids paired with their outcome labels."""

    token_ids = [str(value) for value in parse_jsonish_list(market.get("clobTokenIds"))]
    outcomes = [str(value) for value in parse_jsonish_list(market.get("outcomes"))]
    pairs = []
    for index, token_id in enumerate(token_ids):
        outcome = outcomes[index] if index < len(outcomes) else None
        pairs.append((token_id, outcome))
    return pairs


def infer_winning_outcome(
    outcomes: list[Any], outcome_prices: list[float | None]
) -> tuple[str | None, float | None]:
    """Infer final winning outcome from the highest final outcome price."""

    priced = [
        (str(outcome), price)
        for outcome, price in zip(outcomes, outcome_prices, strict=False)
        if price is not None
    ]
    if not priced:
        return None, None
    outcome, price = max(priced, key=lambda item: item[1])
    return outcome, price


def outcome_price_for(
    outcomes: list[Any], outcome_prices: list[float | None], outcome_name: str
) -> float | None:
    """Return the price for a named outcome, case-insensitively."""

    for outcome, price in zip(outcomes, outcome_prices, strict=False):
        if str(outcome).lower() == outcome_name.lower():
            return price
    return None


def extract_tag_slugs(market: dict[str, Any]) -> list[str]:
    """Extract tag slugs from market-level or event-level Gamma payloads."""

    slugs: list[str] = []
    market_tags = market.get("tags")
    for tag in market_tags if isinstance(market_tags, list) else []:
        if isinstance(tag, dict) and tag.get("slug"):
            slugs.append(str(tag["slug"]))
    raw_events = market.get("events")
    events = raw_events if isinstance(raw_events, list) else []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_tags = event.get("tags")
        for tag in event_tags if isinstance(event_tags, list) else []:
            if isinstance(tag, dict) and tag.get("slug"):
                slugs.append(str(tag["slug"]))
    return sorted(set(slugs))


def parse_jsonish_list(value: Any) -> list[Any]:
    """Parse Gamma fields that may be JSON strings or native lists."""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def parse_float(value: Any) -> float | None:
    """Parse optional numeric fields from Gamma string/number values."""

    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_history_frame_from_raw(raw_dir: Path) -> pd.DataFrame:
    """Build a normalized price-history frame from raw CLOB history JSON files."""

    rows: list[dict[str, Any]] = []
    for path in sorted((raw_dir / "history").glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            logger.warning("polymarket_history_json_invalid", path=str(path))
            continue
        rows.extend(price_history_rows(payload))
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(
            columns=["market_id", "token_id", "outcome", "timestamp", "price", "source_file"]
        )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "price"])
    frame["price"] = frame["price"].clip(0.001, 0.999)
    return frame.sort_values(["market_id", "outcome", "timestamp"]).reset_index(drop=True)


def price_history_rows(raw_file_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized rows from one raw CLOB prices-history payload."""

    payload = raw_file_payload.get("payload")
    history = payload.get("history") if isinstance(payload, dict) else []
    if not isinstance(history, list):
        return []
    rows = []
    for item in history:
        if not isinstance(item, dict):
            continue
        timestamp = history_timestamp(item)
        price = parse_float(item.get("p") or item.get("price"))
        if timestamp is None or price is None:
            continue
        rows.append(
            {
                "market_id": str(raw_file_payload.get("market_id")),
                "token_id": str(raw_file_payload.get("token_id")),
                "outcome": raw_file_payload.get("outcome"),
                "timestamp": timestamp,
                "price": price,
                "source_file": raw_file_payload.get("source"),
            }
        )
    return rows


def history_timestamp(item: dict[str, Any]) -> datetime | None:
    """Parse a CLOB history timestamp from common response fields."""

    raw_value = item.get("t") or item.get("timestamp") or item.get("time")
    if raw_value is None:
        return None
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError):
        parsed = pd.to_datetime(raw_value, utc=True, errors="coerce")
        if pd.isna(parsed):
            return None
        return cast(datetime, parsed.to_pydatetime())
    if numeric > 10_000_000_000:
        numeric = numeric / 1000
    return datetime.fromtimestamp(numeric, tz=UTC)


def unix_seconds(value: Any) -> int | None:
    """Parse an optional timestamp value to Unix seconds."""

    if value is None:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return int(parsed.timestamp())


def dedupe_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate market list by stable market identifier."""

    seen: set[str] = set()
    output = []
    for market in markets:
        key = market_identifier(market)
        if key in seen:
            continue
        seen.add(key)
        output.append(market)
    return output


def market_identifier(market: dict[str, Any]) -> str:
    """Return a stable identifier for a Gamma market object."""

    for key in ("id", "conditionId", "slug", "questionID"):
        value = market.get(key)
        if value:
            return safe_filename(str(value))
    raise ValueError(f"Market payload is missing a usable identifier: {market.keys()}")


def market_path(raw_dir: Path, *, market_id: str, scope: str) -> Path:
    """Return stable raw-cache path for one market."""

    return raw_dir / "markets" / f"{safe_filename(scope)}_{safe_filename(market_id)}.json"


def history_path(raw_dir: Path, *, market_id: str, token_id: str, interval: str) -> Path:
    """Return stable raw-cache path for one token history."""

    return (
        raw_dir
        / "history"
        / f"{safe_filename(market_id)}_{safe_filename(token_id)}_{safe_filename(interval)}.json"
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def safe_filename(value: str) -> str:
    """Make a value safe for filesystem cache names."""

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")[:180] or "unknown"


def tag_slug(value: str) -> str:
    """Normalize user tag input to a slug."""

    return safe_filename(value.strip().lower().replace(" ", "-"))


def utc_now_iso() -> str:
    """Return current UTC timestamp."""

    return datetime.now(tz=UTC).isoformat()


if __name__ == "__main__":
    main()

```

## 4. Configuration

Pydantic settings class definitions from `src/core/config.py`:
```python
class Settings(BaseSettings):
    """Runtime settings for data ingestion, modeling, and execution."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PM_EDGE_",
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = False

    data_dir: Path = Path("data")
    raw_data_dir: Path = Path("data/raw")
    processed_data_dir: Path = Path("data/processed")

    database_url: str = "sqlite:///data/pm_edge.db"
    supabase_url: str | None = None
    supabase_key: SecretStr | None = None
    postgres_host: str | None = None
    postgres_port: int = 5432
    postgres_db: str | None = None
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None

    polymarket_api_key: SecretStr | None = None
    polymarket_api_secret: SecretStr | None = None
    polymarket_api_passphrase: SecretStr | None = None
    polymarket_base_url: str = "https://clob.polymarket.com"
    polymarket_chain_id: int = 137

    kalshi_api_key: SecretStr | None = None
    kalshi_api_secret: SecretStr | None = None
    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"

    news_api_key: SecretStr | None = None
    etherscan_api_key: SecretStr | None = None
    gdelt_base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"

    use_advanced_features: bool = False
    llm_provider: Literal["ollama", "openai", "claude", "grok"] = "ollama"
    llm_model: str | None = None
    llm_fallback_provider: Literal["openai", "claude", "grok"] = "openai"
    llm_fallback_model: str | None = None
    ollama_host: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("PM_EDGE_OLLAMA_HOST", "OLLAMA_HOST"),
    )
    ollama_model: str = Field(
        default="qwen2.5:32b",
        validation_alias=AliasChoices(
            "PM_EDGE_OLLAMA_DEFAULT_MODEL",
            "PM_EDGE_OLLAMA_MODEL",
            "OLLAMA_DEFAULT_MODEL",
            "OLLAMA_MODEL",
        ),
    )
    ollama_fallback_model: str = Field(
        default="llama3.3:70b",
        validation_alias=AliasChoices("PM_EDGE_OLLAMA_FALLBACK_MODEL", "OLLAMA_FALLBACK_MODEL"),
    )
    high_value_fallback: bool = Field(
        default=True,
        validation_alias=AliasChoices("PM_EDGE_HIGH_VALUE_FALLBACK", "HIGH_VALUE_FALLBACK"),
    )
    llm_fallback_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices("PM_EDGE_LLM_FALLBACK_THRESHOLD", "LLM_FALLBACK_THRESHOLD"),
    )
    llm_cache_dir: Path = Path("data/processed/llm_cache")
    llm_max_requests_per_minute: int = Field(default=20, ge=1)
    llm_max_batch_cost_usd: float = Field(default=5.0, ge=0.0)
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    grok_api_key: SecretStr | None = None

    defillama_base_url: str = "https://api.llama.fi"
    dune_api_key: SecretStr | None = None
    arkham_api_key: SecretStr | None = None

    http_timeout_seconds: float = Field(default=20.0, ge=1.0)
    http_max_connections: int = Field(default=20, ge=1)
    retry_attempts: int = Field(default=3, ge=1)
    retry_min_seconds: float = Field(default=0.25, ge=0.0)
    retry_max_seconds: float = Field(default=4.0, ge=0.0)

    paper_trading: bool = True
    max_order_notional_usd: float = Field(default=100.0, gt=0)
    max_portfolio_notional_usd: float = Field(default=1_000.0, gt=0)
    paper_trader_interval_seconds: int = Field(default=900, ge=1)
    paper_trader_virtual_capital_usd: float = Field(default=10_000.0, gt=0)
    paper_trader_min_volume_usd: float = Field(default=500_000.0, ge=0)
    paper_trader_max_markets: int = Field(default=50, ge=1)
    paper_trader_review_mode: bool = True
    paper_trader_review_threshold: float = Field(default=0.08, ge=0.0)
    paper_trader_review_timeout_seconds: int = Field(default=0, ge=0)
    paper_trader_state_path: Path = Path("data/processed/live_paper/state.json")
    paper_trader_audit_log_path: Path = Path("data/processed/live_paper/audit.jsonl")
    paper_trader_review_flag_path: Path = Path("data/processed/live_paper/review_approval.txt")
    paper_trader_alert_webhook_url: SecretStr | None = None
    paper_trader_telegram_bot_token: SecretStr | None = None
    paper_trader_telegram_chat_id: str | None = None
    paper_trader_discord_webhook_url: SecretStr | None = None
    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    telegram_rate_limit_seconds: float = Field(default=1.0, ge=0.0)
    fear_layer_enabled: bool = False
    quarter_kelly: bool = False
    min_post_cost_edge: float = Field(default=0.05, ge=0.0)
    liquidity_harvest_mode: bool = False

    @model_validator(mode="after")
    def resolve_relative_paths(self) -> Settings:
        """Resolve project data paths from repo root to avoid cwd-dependent writes."""

        path_fields = [
            "data_dir",
            "raw_data_dir",
            "processed_data_dir",
            "llm_cache_dir",
            "paper_trader_state_path",
            "paper_trader_audit_log_path",
            "paper_trader_review_flag_path",
        ]
        for field_name in path_fields:
            resolved = resolve_repo_path(getattr(self, field_name))
            if resolved is not None:
                setattr(self, field_name, resolved)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_live_trading_enabled(self) -> bool:
        """Return whether live trading is explicitly enabled."""

        return not self.paper_trading and self.environment == "production"
```

Configuration highlights:
- `.env` variable prefix: `PM_EDGE_`
- Polymarket defaults: `polymarket_base_url="https://clob.polymarket.com"`, `polymarket_chain_id=137`, credentials default to `None`.
- Kalshi defaults: `kalshi_base_url="https://api.elections.kalshi.com/trade-api/v2"`, credentials default to `None`.
- News/GDELT defaults: `news_api_key=None`, `gdelt_base_url="https://api.gdeltproject.org/api/v2/doc/doc"`.
- LLM defaults: `llm_provider="ollama"`, `ollama_host="http://localhost:11434"`, `ollama_model="qwen2.5:32b"`, `ollama_fallback_model="llama3.3:70b"`.
- On-chain provider defaults: `defillama_base_url="https://api.llama.fi"`; Dune, Arkham, and Etherscan keys default to `None`.
- Telegram defaults: disabled by default; bot token/chat id default to `None`; rate limit defaults to 1 second.

Full `.env.example` contents, with secret-like values redacted if present:
```dotenv
# Copy to .env and fill in local credentials.

PM_EDGE_ENVIRONMENT=development
PM_EDGE_DEBUG=false
PM_EDGE_LOG_LEVEL=INFO
PM_EDGE_LOG_JSON=false

# Local development defaults to SQLite. Use a Postgres URL for Supabase-style deployments.
PM_EDGE_DATABASE_URL=sqlite:///data/pm_edge.db
PM_EDGE_SUPABASE_URL=
PM_EDGE_SUPABASE_KEY=
PM_EDGE_POSTGRES_HOST=
PM_EDGE_POSTGRES_PORT=5432
PM_EDGE_POSTGRES_DB=
PM_EDGE_POSTGRES_USER=
PM_EDGE_POSTGRES_PASSWORD=

# Prediction market APIs
PM_EDGE_POLYMARKET_API_KEY=
PM_EDGE_POLYMARKET_API_SECRET=
PM_EDGE_POLYMARKET_API_PASSPHRASE=
PM_EDGE_POLYMARKET_BASE_URL=https://clob.polymarket.com
PM_EDGE_POLYMARKET_CHAIN_ID=137

PM_EDGE_KALSHI_API_KEY=
PM_EDGE_KALSHI_API_SECRET=
PM_EDGE_KALSHI_BASE_URL=https://api.elections.kalshi.com/trade-api/v2

# Optional data providers
PM_EDGE_NEWS_API_KEY=
PM_EDGE_ETHERSCAN_API_KEY=
PM_EDGE_GDELT_BASE_URL=https://api.gdeltproject.org/api/v2/doc/doc

# Optional advanced feature providers
PM_EDGE_USE_ADVANCED_FEATURES=false
PM_EDGE_LLM_PROVIDER=ollama
PM_EDGE_LLM_MODEL=
PM_EDGE_OLLAMA_HOST=http://localhost:11434
PM_EDGE_OLLAMA_DEFAULT_MODEL=qwen2.5:32b
PM_EDGE_OLLAMA_FALLBACK_MODEL=llama3.3:70b
PM_EDGE_HIGH_VALUE_FALLBACK=true
PM_EDGE_LLM_FALLBACK_THRESHOLD=0.75
PM_EDGE_LLM_FALLBACK_PROVIDER=openai
PM_EDGE_LLM_FALLBACK_MODEL=gpt-4o-mini
PM_EDGE_LLM_CACHE_DIR=data/processed/llm_cache
PM_EDGE_LLM_MAX_REQUESTS_PER_MINUTE=20
PM_EDGE_LLM_MAX_BATCH_COST_USD=5
PM_EDGE_OPENAI_API_KEY=
PM_EDGE_ANTHROPIC_API_KEY=
PM_EDGE_GROK_API_KEY=
PM_EDGE_DEFILLAMA_BASE_URL=https://api.llama.fi
PM_EDGE_DUNE_API_KEY=
PM_EDGE_ARKHAM_API_KEY=

# Runtime controls
PM_EDGE_PAPER_TRADING=true
PM_EDGE_MAX_ORDER_NOTIONAL_USD=100
PM_EDGE_MAX_PORTFOLIO_NOTIONAL_USD=1000
PM_EDGE_PAPER_TRADER_INTERVAL_SECONDS=900
PM_EDGE_PAPER_TRADER_VIRTUAL_CAPITAL_USD=10000
PM_EDGE_PAPER_TRADER_MIN_VOLUME_USD=500000
PM_EDGE_PAPER_TRADER_MAX_MARKETS=50
PM_EDGE_PAPER_TRADER_REVIEW_MODE=true
PM_EDGE_PAPER_TRADER_REVIEW_THRESHOLD=0.08
PM_EDGE_PAPER_TRADER_REVIEW_TIMEOUT_SECONDS=0
PM_EDGE_PAPER_TRADER_STATE_PATH=data/processed/live_paper/state.json
PM_EDGE_PAPER_TRADER_AUDIT_LOG_PATH=data/processed/live_paper/audit.jsonl
PM_EDGE_PAPER_TRADER_REVIEW_FLAG_PATH=data/processed/live_paper/review_approval.txt
PM_EDGE_PAPER_TRADER_ALERT_WEBHOOK_URL=
PM_EDGE_PAPER_TRADER_TELEGRAM_BOT_TOKEN=
PM_EDGE_PAPER_TRADER_TELEGRAM_CHAT_ID=
PM_EDGE_PAPER_TRADER_DISCORD_WEBHOOK_URL=
PM_EDGE_TELEGRAM_ENABLED=false
PM_EDGE_TELEGRAM_BOT_TOKEN=
PM_EDGE_TELEGRAM_CHAT_ID=
PM_EDGE_TELEGRAM_RATE_LIMIT_SECONDS=1
PM_EDGE_FEAR_LAYER_ENABLED=false
PM_EDGE_QUARTER_KELLY=false
PM_EDGE_MIN_POST_COST_EDGE=0.05
PM_EDGE_LIQUIDITY_HARVEST_MODE=false
PM_EDGE_HTTP_TIMEOUT_SECONDS=20
PM_EDGE_RETRY_ATTEMPTS=3
```

## 5. Existing Collection Surface

| File Path | Function/Class | Description |
| --- | --- | --- |
| scripts/backfill_polymarket.py | (module) | Contains external provider URL references or module-level data-source configuration. |
| scripts/backfill_polymarket.py | BackfillConfig | Runtime configuration for the Polymarket public backfill. |
| scripts/backfill_polymarket.py | PolymarketBackfiller | Async public Polymarket backfill client with local raw-cache persistence. |
| scripts/backfill_polymarket.py | __init__ | Uses an HTTP client to access an external or configurable data source. |
| scripts/backfill_polymarket.py | fetch_markets | Fetch markets through Gamma keyset pagination. |
| scripts/backfill_polymarket.py | fetch_price_histories | Fetch CLOB price history for resolved markets with CLOB token IDs. |
| scripts/backfill_polymarket.py | fetch_price_history_payload | Fetch CLOB price history, chunking long bounded requests when needed. |
| scripts/generate_signals.py | (module) | Contains external provider URL references or module-level data-source configuration. |
| scripts/generate_signals.py | build_advanced_context | Build optional advanced signal context for one market. |
| src/backtesting/backtester.py | Backtester | Run deterministic walk-forward signal backtests from feature/signal rows. |
| src/core/client.py | PredictionMarketClient | Async facade over PMXT with direct SDK fallbacks. |
| src/core/client.py | __init__ | Collects, normalizes, or accesses Polymarket market data. |
| src/core/client.py | _fetch_markets_from_backend | Collects, normalizes, or accesses Polymarket market data. |
| src/core/client.py | fetch_markets | Fetch active markets from PMXT first, then direct venue adapters. |
| src/core/client.py | fetch_order_book | Fetch a normalized order book snapshot. |
| src/core/config.py | (module) | Contains external provider URL references or module-level data-source configuration. |
| src/core/config.py | Settings | Runtime settings for data ingestion, modeling, and execution. |
| src/core/models.py | BacktestBet | Simulated backtest bet and realized outcome. |
| src/core/models.py | BacktestRun | Backtest run metadata and aggregate output. |
| src/core/models.py | FeatureVectorRecord | Materialized feature vector used for model training or scoring. |
| src/core/models.py | Market | Unified market representation across prediction market venues. |
| src/core/models.py | MarketPrice | Historical market price snapshot. |
| src/core/models.py | PollAggregateRecord | Daily weighted poll aggregate for an event or market. |
| src/core/models.py | PollObservation | Normalized poll observation for an event or market. |
| src/core/models.py | Position | Current or historical portfolio position. |
| src/core/models.py | Resolution | Final market outcome and resolution metadata. |
| src/core/models.py | SentimentVectorRecord | Daily news and sentiment feature vector linked to a market/event. |
| src/core/models.py | Trade | Executed trade event. |
| src/core/scanner.py | _fetch_snapshots | Data ingestion or collection-related entry point. |
| src/core/scanner.py | fetch_one | Data ingestion or collection-related entry point. |
| src/data/database.py | HistoricalMarketStore | Small SQLModel repository for markets, prices, and resolutions. |
| src/data/llm_news_processor.py | LLMNewsProcessor | Generate cached, structured news signals using a configurable LLM provider. |
| src/data/llm_news_processor.py | __init__ | Uses an HTTP client to access an external or configurable data source. |
| src/data/news_sentiment.py | (module) | Contains external provider URL references or module-level data-source configuration. |
| src/data/news_sentiment.py | NewsSentimentEngine | Fetch, link, score, and persist news sentiment velocity features. |
| src/data/news_sentiment.py | __init__ | Uses an HTTP client to access an external or configurable data source. |
| src/data/news_sentiment.py | fetch_gdelt | Fetch normalized articles from GDELT's document API. |
| src/data/news_sentiment.py | fetch_newsapi | Fetch normalized articles from NewsAPI when credentials are configured. |
| src/data/onchain_processor.py | (module) | Contains external provider URL references or module-level data-source configuration. |
| src/data/onchain_processor.py | OnChainProcessor | Fetch and normalize crypto on-chain metrics with safe fallbacks. |
| src/data/onchain_processor.py | __init__ | Uses an HTTP client to access an external or configurable data source. |
| src/data/onchain_processor.py | _fetch_defillama_protocol | Collects or normalizes crypto/on-chain provider data. |
| src/data/onchain_processor.py | fetch_market_metrics | Fetch metrics for crypto-linked markets, or return None for non-crypto markets. |
| src/data/poll_aggregator.py | PollAggregate | Weighted aggregate for one candidate/outcome. |
| src/data/poll_aggregator.py | PollAggregator | Normalize, weight, aggregate, and persist polling data. |
| src/data/poll_aggregator.py | PollRecord | Clean poll result for one candidate/outcome. |
| src/data/resolved_backfill.py | BackfillConfig | Controls for resolved-market backfill loading and deduplication. |
| src/data/resolved_backfill.py | ResolvedMarketBackfill | Load and normalize resolved market rows from local historical files. |
| src/execution/paper_trader.py | (module) | Contains external provider URL references or module-level data-source configuration. |
| src/execution/paper_trader.py | PaperTrader | Run the live paper loop: markets -> signals -> Kelly targets -> paper decisions. |
| src/execution/paper_trader.py | _advanced_context | Collects or processes external news data for market features. |
| src/execution/paper_trader.py | _fetch_markets | Data ingestion or collection-related entry point. |
| src/features/feature_store.py | FeatureStore | Combine poll, sentiment, cross-market, and microstructure features. |
| src/features/feature_store.py | poll_features | Flatten latest poll aggregates into model features. |
| src/monitoring/alerts.py | AlertManager | Send important live-paper events to console and optional webhooks. |
| src/monitoring/alerts.py | __init__ | Uses an HTTP client to access an external or configurable data source. |
| src/monitoring/telegram_alerts.py | TelegramNotifier | Async Telegram notifier with rate limiting and graceful no-op fallback. |
| src/monitoring/telegram_alerts.py | __init__ | Uses an HTTP client to access an external or configurable data source. |

## 6. Sanity Checks

- Total disk usage of `data/`: `358M	data`
- Total LOC in `src/`: `9299`
- Test count via `pytest --collect-only -q`: `70`

Raw LOC command output:
```text
169 src/backtesting/rubric.py
     213 src/backtesting/metrics.py
      33 src/backtesting/__init__.py
      91 src/backtesting/data_split.py
     338 src/backtesting/backtester.py
     788 src/backtesting/deep_analysis.py
     365 src/backtesting/portfolio_backtester.py
     241 src/core/scanner.py
     163 src/core/config.py
     223 src/core/models.py
     570 src/core/client.py
      41 src/core/__init__.py
      23 src/strategies/__init__.py
     568 src/strategies/liquidity_provider.py
     194 src/strategies/edge_detector.py
      61 src/strategies/structural_scanner.py
      61 src/features/micro_round.py
     279 src/features/feature_store.py
     114 src/features/advanced_features.py
     150 src/features/cross_market.py
      22 src/features/__init__.py
     138 src/features/fear_layer.py
     131 src/features/onchain_enhanced.py
      89 src/utils/logging.py
      27 src/utils/paths.py
      13 src/utils/__init__.py
     105 src/models/baselines.py
      23 src/models/__init__.py
     468 src/models/trainer.py
      90 src/models/gbdt.py
     183 src/execution/paper.py
      32 src/execution/__init__.py
      84 src/execution/risk_engine.py
     640 src/execution/paper_trader.py
     161 src/execution/portfolio.py
     103 src/monitoring/alerts.py
      22 src/monitoring/__init__.py
      97 src/monitoring/dashboard.py
     224 src/monitoring/telegram_alerts.py
     179 src/monitoring/performance_tracker.py
     642 src/data/llm_news_processor.py
      55 src/data/resolved_backfill.py
     180 src/data/database.py
      25 src/data/__init__.py
     324 src/data/news_sentiment.py
     344 src/data/poll_aggregator.py
     213 src/data/onchain_processor.py
    9299 total
```

Raw pytest collection summary:
```text
70 tests collected in 1.78s
```
