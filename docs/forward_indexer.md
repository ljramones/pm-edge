# Forward Indexer

The forward indexer is the producer side of the new data layer. It captures public Polymarket and Kalshi market metadata, top-of-book snapshots, and trade events into partitioned parquet files. It is read-only against venues and does not use authenticated trading endpoints or place orders.

## Architecture

```text
Polymarket CLOB REST + WS        Kalshi REST + WS
        |                              |
        v                              v
  VenueIndexer implementations in src/data/forward_indexer/
        |                              |
        +------------+-----------------+
                     v
            In-memory BookState
                     |
             15-second emit tick
                     |
                     v
          BufferedParquetWriter
                     |
                     v
data/raw/forward_index/
  order_book_snapshots/venue=<venue>/date=<YYYY-MM-DD>/*.parquet
  trade_events/venue=<venue>/date=<YYYY-MM-DD>/*.parquet
  market_metadata_snapshots/venue=<venue>/date=<YYYY-MM-DD>/*.parquet
```

The VPS stores only parquet. The laptop-side DuckDB layer is intentionally out of scope for this phase.

## Captured Tables

Every table includes `schema_version`.

- `order_book_snapshots`: top-N bid/ask levels, top bid/ask, mid, spread, source.
- `trade_events`: venue trade id when available, token/outcome id, price, size, side, timestamp.
- `market_metadata_snapshots`: market lifecycle/status, 24h volume, liquidity, end date, raw venue JSON.

Default book depth is 5 levels per side.

## Local Development Quickstart

Dry-run discovery with no writes:

```bash
python -m scripts.forward_index --dry-run --venues polymarket,kalshi
```

Diagnostic polling mode, writing to a temp folder:

```bash
python -m scripts.forward_index \
  --venues polymarket \
  --polling-mode \
  --emit-cadence-seconds 15 \
  --output-dir /tmp/pm-edge-forward-index
```

Default production-style run:

```bash
python -m scripts.forward_index \
  --venues polymarket,kalshi \
  --emit-cadence-seconds 15 \
  --discovery-cadence-seconds 300 \
  --book-depth-levels 5 \
  --min-24h-volume-usd 1000 \
  --max-spread-cents 20 \
  --output-dir data/raw/forward_index
```

## VPS Deploy Quickstart

On a fresh Ubuntu 24.04 droplet:

```bash
sudo PM_EDGE_GIT_REMOTE=https://github.com/YOURUSERNAME/pm-edge.git \
  bash deploy/forward_indexer/setup_vps.sh
```

Then edit:

```bash
sudo nano /opt/pm-edge/.env
sudo systemctl restart forward-indexer.service
journalctl -u forward-indexer.service -f
```

The service runs as non-root user `pmedge` and writes to `/opt/pm-edge/data/raw/forward_index`.

## Laptop Sync

From the laptop:

```bash
PM_EDGE_VPS_HOST=pmedge@YOUR_DROPLET_IP \
  bash deploy/forward_indexer/rsync_to_laptop.sh
```

The script is idempotent and uses `--ignore-existing` so completed parquet parts are not re-copied.

## Capacity Estimate

Rough depth-5 book snapshot shape:

- Fixed fields and parquet overhead: ~100-200 bytes.
- 10 price levels x 2 float64 values: 160 bytes before encoding/compression.
- Practical parquet size estimate after encoding/compression: ~250-600 bytes per snapshot depending on metadata and row-group size.

At default cadence:

- One market: 5,760 snapshots/day.
- 200 active markets: 1,152,000 snapshots/day.
- Estimated daily snapshot parquet: ~300 MB to 700 MB uncompressed-equivalent, typically materially less on disk after parquet compression and repeated schemas.
- Trade events are bursty and venue-dependent; expect small normal days and spikes during major events.

Default activity filter estimate:

- Expected active markets after `$1,000` 24h volume OR spread `< $0.20`: 200-500 across both venues.
- This is an educated guess. First-day operation should report actual pass/fail counts at `$100`, `$1,000`, and `$10,000`.

Runway on the target `s-2vcpu-2gb` 60 GB tier:

- At 500 MB/day on disk: ~120 days before raw disk exhaustion, ignoring OS/repo/log space.
- With weekly rsync and periodic archival/cleanup, a 60 GB VPS is sufficient for the initial producer role.
- If observed growth exceeds 1.5 GB/day, switch to tighter filters, compression review, or shorter VPS retention.

Memory:

- Book state is bounded by `markets * depth * sides`.
- 500 markets at depth 5 is only thousands of levels in memory; Python overhead should remain comfortably below the default 1024 MB ceiling.
- The writer force-flushes if process memory exceeds `--max-memory-mb`.

## Inspection Recipes

DuckDB examples for synced parquet:

```sql
SELECT venue, count(*) AS rows
FROM read_parquet('data/raw/forward_index/order_book_snapshots/*/*/*.parquet')
GROUP BY venue;
```

```sql
SELECT venue, market_id, max(timestamp_utc) AS last_seen, count(*) AS snapshots
FROM read_parquet('data/raw/forward_index/order_book_snapshots/*/*/*.parquet')
GROUP BY venue, market_id
ORDER BY last_seen DESC
LIMIT 20;
```

```sql
SELECT venue, date_trunc('hour', timestamp_utc) AS hour, count(*) AS trades
FROM read_parquet('data/raw/forward_index/trade_events/*/*/*.parquet')
GROUP BY venue, hour
ORDER BY hour DESC;
```

```sql
SELECT venue, avg(spread) AS avg_spread, approx_quantile(spread, 0.95) AS p95_spread
FROM read_parquet('data/raw/forward_index/order_book_snapshots/*/*/*.parquet')
WHERE spread IS NOT NULL
GROUP BY venue;
```

## Failure Modes

- `*_ws_reconnect`: WebSocket dropout. The indexer backs off with jitter and refreshes full REST books before continuing.
- `forward_indexer_memory_ceiling_exceeded`: process memory exceeded `--max-memory-mb`; buffers were force-flushed.
- Persistent HTTP 429s: venue public endpoints are rate-limiting. The indexer backs off up to 60 seconds; if persistent, stop and lower market scope.
- Missing snapshots for a market: the market may have failed the activity filter, REST book initialization failed, or the WebSocket reconnect loop is stuck.
- Parquet read failure: kill criterion. Any part that cannot be opened by `pyarrow.parquet.ParquetFile` should block merge/deploy.

## Kill Criteria

This phase should not be considered production-ready unless a target VPS soak test shows:

- 15-second emit cadence sustained on 200+ filtered markets for 1 hour.
- WebSocket dropout rate below 5% per hour.
- No persistent public endpoint rate limits.
- Parquet readable by pyarrow and DuckDB.
- Memory bounded for the full soak.
- Interrupted rsync does not lose, duplicate, or corrupt completed parquet parts.
