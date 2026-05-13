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

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"
RAW_DIR = Path("data/raw/polymarket")
PROCESSED_DIR = Path("data/processed")
RESOLVED_PARQUET = PROCESSED_DIR / "resolved_markets.parquet"


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
                try:
                    payload = await self.request_json(
                        f"{CLOB_BASE_URL}/prices-history", params=params
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
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        page_size=args.page_size,
        request_delay=args.request_delay,
        history_interval=args.history_interval,
        history_fidelity=args.history_fidelity,
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
