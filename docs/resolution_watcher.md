# Resolution Watcher

## Purpose

The resolution watcher detects prediction markets that have resolved and writes
binary outcomes to a partitioned parquet table. Strategy validation needs these
resolution rows because simulated fills only become meaningful once the market's
official outcome is known.

The watcher is a consumer of the forward-index archive. It reads
`market_metadata_snapshots` and `order_book_snapshots`, calls public venue market
endpoints for resolution outcomes, and writes `resolved_market_outcomes`.

## Output Table

Rows are written under:

```text
data/raw/resolved_market_outcomes/venue=<venue>/date=<resolution_date>/part-*.parquet
```

Schema:

- `schema_version`
- `venue`
- `market_id`
- `resolution_timestamp_utc`
- `venue_resolved_at_utc`
- `resolved_value`
- `resolution_source`
- `final_top_bid`
- `final_top_ask`
- `final_spread`
- `final_snapshot_timestamp_utc`
- `metadata_snapshot_id`

`resolved_value` is `1.0` for YES and `0.0` for NO in v0. Fractional outcomes are
accepted by the schema but not actively modeled.

## Venue Sources

Polymarket:

- Detection comes from local metadata snapshots whose latest row indicates a
  closed, settled, or resolved market.
- Outcome fetch uses `GET {polymarket_base_url}/markets/{condition_id}`.
- v0 parses common binary outcome fields such as `winningOutcome`,
  `resolvedOutcome`, `winningOutcomeIndex`, or numeric settlement values.

Kalshi:

- Detection comes from local metadata snapshots whose latest row indicates
  `closed`, `settled`, or `resolved`.
- Outcome fetch uses `GET {kalshi_base_url}/markets/{ticker}`.
- v0 parses `result`, `settlement_result`, or `settlement_value`.

## Local Run

```bash
PM_EDGE_RESOLUTION_WATCHER_DRY_RUN=true \
PM_EDGE_RESOLUTION_WATCHER_POLL_CADENCE_SECONDS=30 \
python -m data.resolution_watcher.runner
```

Useful settings:

- `PM_EDGE_RESOLUTION_WATCHER_SOURCE_DIR`
- `PM_EDGE_RESOLUTION_WATCHER_OUTPUT_DIR`
- `PM_EDGE_RESOLUTION_WATCHER_VENUES_ENABLED`
- `PM_EDGE_RESOLUTION_WATCHER_POLL_CADENCE_SECONDS`
- `PM_EDGE_RESOLUTION_WATCHER_DRY_RUN`

The service emits `resolution_watcher_cycle` and `resolution_watcher_heartbeat`
logs. Heartbeats include markets checked, markets resolved in the cycle, and
total resolved since process start.

## VPS Deployment

The systemd unit lives at:

```text
deploy/resolution_watcher/systemd/resolution-watcher.service
```

The setup skeleton:

```bash
sudo deploy/resolution_watcher/setup_vps.sh
sudo systemctl start resolution-watcher.service
sudo journalctl -u resolution-watcher -f
```

The setup script assumes the pm-edge checkout and virtual environment already
exist at `/opt/pm-edge`.

## v0 Limitations

- No historical backfill. It watches forward from process start.
- Polling only. No real-time WebSocket-based resolution detection.
- No dispute or contested-market state handling.
- Binary YES/NO outcomes only for active interpretation.
- Basic retry only for venue API calls.
- No cross-venue or arbitrage logic.

These are explicitly deferred to v1.

## v1 Roadmap

- Historical resolution backfill.
- Dispute and clarification tracking.
- Richer venue-specific settlement parsing.
- Multi-outcome and fractional payoff handling.
- Resolution update records when a venue revises settlement.
- Integration with the execution simulator and strategy-validation reports.
