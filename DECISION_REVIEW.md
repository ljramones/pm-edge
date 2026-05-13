# Forward Indexer Decision Review

Generated: 2026-05-13

## 1. Kalshi Base URL Verification

**Question:** Should the indexer use the existing `https://api.elections.kalshi.com/trade-api/v2` base URL or the current canonical `https://external-api.kalshi.com/trade-api/v2` URL?

**Default chosen:** `https://external-api.kalshi.com/trade-api/v2`.

**Verification:** A single unauthenticated `GET /markets?limit=1` was run against both URLs. Both returned HTTP 200 with market payloads.

**Rationale:** Both work today, but `external-api.kalshi.com` is the canonical public API hostname. `Settings.kalshi_base_url` now defaults to the canonical URL.

**Cost of changing later:** Low. This is a single settings default and can be overridden with `PM_EDGE_KALSHI_BASE_URL`.

## 2. Trade Capture Cadence

**Question:** Capture trades only at the 15-second book snapshot tick, or capture higher-frequency trade events from WebSocket streams?

**Default chosen:** WebSocket trade stream when available.

**Rationale:** Liquidity and simulator work needs event-time trade prints, not only tick-time samples. Trade rows are buffered separately from order-book snapshots and flushed to `trade_events`.

**Storage implication:** Trade storage can grow faster than snapshot storage during high-volume events. It is still expected to be smaller than full-depth order-book event logs because the default book output is periodic snapshots.

**Cost of changing later:** Low to medium. The table already supports event-time trades; disabling trade capture would be a runner/indexer config change.

## 3. Activity Filter Threshold

**Question:** Is `$1,000` 24h volume OR spread `< $0.20` the right default subscription filter?

**Default chosen:** Keep `$1,000` 24h volume OR spread `< $0.20`.

**Rationale:** It is permissive enough to capture early liquidity candidates while avoiding obvious dead markets. Metadata is still captured for markets that fail the filter.

**First-day review needed:** After one day, compute pass/fail counts for thresholds `$100`, `$1,000`, and `$10,000`, plus spread cutoffs around `$0.10`, `$0.20`, and `$0.30`.

**Cost of changing later:** Low. It is exposed as `--min-24h-volume-usd`, `--max-spread-cents`, and `PM_EDGE_` settings.

## 4. Reconnect Loop Strategy

**Question:** How should WebSocket reconnects handle venue dropouts?

**Default chosen:** Exponential backoff with jitter, capped at 60 seconds. On reconnect, refresh the full book from REST before consuming new diffs.

**Rationale:** Full REST refresh after reconnect favors data integrity over continuity. Snapshot gaps are acceptable and visible through timestamp spacing; silently applying diffs after a gap is not.

**Data-integrity guarantee:** The indexer does not claim complete event-sourced book history. It claims periodic top-of-book snapshots from the latest known in-memory state, with REST refresh after reconnect.

**Cost of changing later:** Medium. The reconnect policy is centralized in venue indexers, but stronger guarantees would require sequence-number validation and gap markers per venue.

## 5. Parquet Partition Granularity

**Question:** Partition parquet output by day or by hour?

**Default chosen:** Per-day partitions under `table/venue=<venue>/date=<YYYY-MM-DD>/`.

**Rationale:** Daily partitions reduce small-file pressure and simplify rsync. The producer runs on a small VPS and should prioritize write efficiency.

**Read-side implication:** DuckDB queries for narrow time windows may scan more data than hourly partitions would. If query latency becomes a problem, a later compaction or hourly partition phase can be added.

**Cost of changing later:** Medium. Partition layout is part of the lake contract; changing it should include a migration/compatibility plan for existing parquet.
