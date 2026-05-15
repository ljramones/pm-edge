"""Generate a static operational status page for the forward indexer."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, cast

import duckdb
from jinja2 import Template

from core.config import get_settings  # type: ignore[import-untyped]

DEFAULT_DATA_DIR = Path("/opt/pm-edge/data/raw/forward_index")
DEFAULT_OUTPUT = Path("/opt/pm-edge/data/ops_status.html")
DEFAULT_SERVICE_NAME = "forward-indexer"

TABLES = ("order_book_snapshots", "trade_events", "market_metadata_snapshots")
WINDOWS = (1, 6, 24)

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="60">
  <title>pm-edge forward indexer status</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; }
    h1 { margin-bottom: 0; }
    section { border: 1px solid #d0d7de; border-radius: 6px; margin: 18px 0; padding: 16px; }
    table { border-collapse: collapse; width: 100%; margin-top: 8px; }
    th, td { border: 1px solid #d0d7de; padding: 6px 8px; text-align: left; }
    th { background: #f6f8fa; }
    .green { border-left: 8px solid #2da44e; }
    .yellow { border-left: 8px solid #bf8700; }
    .red { border-left: 8px solid #cf222e; }
    .muted { color: #57606a; }
    pre { background: #f6f8fa; border: 1px solid #d0d7de; padding: 12px; overflow-x: auto; }
  </style>
</head>
<body>
  <h1>pm-edge forward indexer status</h1>
  <p class="muted">Generated at {{ generated_at }}</p>

  <section class="{{ service.color }}">
    <h2>Service health</h2>
    <table>
      <tr><th>Active state</th><td>{{ service.active_state }}</td></tr>
      <tr><th>Uptime</th><td>{{ service.uptime }}</td></tr>
      <tr><th>Current PID</th><td>{{ service.pid }}</td></tr>
      <tr><th>NRestarts</th><td>{{ service.restarts }}</td></tr>
      <tr><th>Memory current</th><td>{{ service.memory_current_mb }}</td></tr>
      <tr><th>Memory peak</th><td>{{ service.memory_peak_mb }}</td></tr>
      <tr><th>Memory cap</th><td>{{ memory_cap_mb }} MB</td></tr>
    </table>
  </section>

  <section>
    <h2>Heartbeat</h2>
    <table>
      <tr><th>Most recent heartbeat</th><td>{{ heartbeat.latest_timestamp }}</td></tr>
      <tr><th>Heartbeat age</th><td>{{ heartbeat.age_seconds }} seconds</td></tr>
      <tr><th>Snapshots/sec current</th><td>{{ heartbeat.current_snapshots_per_second }}</td></tr>
      <tr><th>Snapshots/sec rolling 15m avg</th><td>{{ heartbeat.avg_snapshots_per_second }}</td></tr>
      <tr><th>Markets tracked</th><td>{{ heartbeat.markets_tracked }}</td></tr>
      <tr><th>WebSocket connections</th><td>{{ heartbeat.websocket_connections }}</td></tr>
      <tr><th>Errors since last heartbeat</th><td>{{ heartbeat.errors_since_last }}</td></tr>
      <tr><th>Dedupe keys retained</th><td>{{ heartbeat.dedupe_keys_retained }}</td></tr>
    </table>
  </section>

  <section>
    <h2>Capture rate</h2>
    <h3>Snapshots</h3>
    {{ capture.snapshot_html }}
    <h3>Trades</h3>
    {{ capture.trade_html }}
  </section>

  <section>
    <h2>Storage</h2>
    <table>
      <tr><th>Total forward index size</th><td>{{ storage.total_size_mb }} MB</td></tr>
      <tr><th>VPS disk free</th><td>{{ storage.disk_free_gb }} GB</td></tr>
      <tr><th>Growth rate</th><td>{{ storage.growth_mb_per_hour }} MB/hour</td></tr>
      <tr><th>Projected days until disk full</th><td>{{ storage.days_until_full }}</td></tr>
    </table>
    {{ storage.table_html }}
  </section>

  <section>
    <h2>Data quality</h2>
    <h3>Kalshi book quality</h3>
    {{ quality.kalshi_html }}
    <h3>Polymarket source breakdown</h3>
    {{ quality.polymarket_html }}
    <h3>Recent gaps</h3>
    {{ quality.gap_html }}
  </section>

  <section>
    <h2>Error log</h2>
    <table>
      <tr><th>Polymarket Gamma retries, 24h</th><td>{{ errors.gamma_retries_24h }}</td></tr>
      <tr><th>WebSocket reconnects, 24h</th><td>{{ errors.websocket_reconnects_24h }}</td></tr>
    </table>
    <pre>{{ errors.recent_errors }}</pre>
  </section>
</body>
</html>
"""


@dataclass(frozen=True)
class ServiceHealth:
    """Rendered systemd service health fields."""

    active_state: str
    uptime: str
    pid: str
    restarts: str
    memory_current_mb: str
    memory_peak_mb: str
    color: str


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--service", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--memory-cap-mb", type=float, default=default_memory_cap_mb())
    args = parser.parse_args(argv)

    started = time.perf_counter()
    try:
        html = build_status_html(
            data_dir=args.data_dir,
            service_name=args.service,
            memory_cap_mb=args.memory_cap_mb,
        )
        write_atomic(html, args.output)
    except Exception as exc:  # pragma: no cover - top-level safety
        print(f"ops_status failed: {exc}", file=sys.stderr)
        return 1

    elapsed = time.perf_counter() - started
    timestamp = datetime.now(tz=UTC).isoformat()
    print(f"{timestamp} wrote={args.output} query_seconds={elapsed:.3f}")
    return 0


def build_status_html(
    *,
    data_dir: Path,
    service_name: str = DEFAULT_SERVICE_NAME,
    memory_cap_mb: float | None = None,
) -> str:
    """Collect status data and render the HTML page."""

    now = datetime.now(tz=UTC)
    cap = memory_cap_mb if memory_cap_mb is not None else default_memory_cap_mb()
    con = duckdb.connect()
    context = {
        "generated_at": now.isoformat(),
        "memory_cap_mb": round(cap, 2),
        "service": get_service_health(service_name, cap, now=now),
        "heartbeat": heartbeat_summary(service_name, now=now),
        "capture": capture_rate_summary(con, data_dir, now),
        "storage": storage_summary(data_dir, now),
        "quality": data_quality_summary(con, data_dir, now),
        "errors": error_log_summary(service_name),
    }
    return Template(HTML_TEMPLATE).render(**context)


def default_memory_cap_mb() -> float:
    """Return the forward indexer's configured memory cap."""

    return cast(float, get_settings().forward_indexer_max_memory_mb)


def get_service_health(
    service_name: str,
    memory_cap_mb: float,
    *,
    now: datetime | None = None,
) -> ServiceHealth:
    """Read systemd service health using `systemctl show`."""

    output = run_command(
        [
            "systemctl",
            "show",
            service_name,
            "--property=ActiveState,MainPID,NRestarts,MemoryCurrent,MemoryPeak,ActiveEnterTimestamp",
        ]
    )
    if output is None:
        return ServiceHealth(
            active_state="unknown",
            uptime="unknown",
            pid="unknown",
            restarts="unknown",
            memory_current_mb="unknown",
            memory_peak_mb="unknown",
            color="yellow",
        )

    values = parse_systemctl_show(output)
    active_state = values.get("ActiveState", "unknown")
    restarts = parse_int(values.get("NRestarts"))
    current_mb = bytes_to_mb(parse_int(values.get("MemoryCurrent")))
    peak_mb = bytes_to_mb(parse_int(values.get("MemoryPeak")))
    active_since = parse_systemd_timestamp(values.get("ActiveEnterTimestamp"))
    uptime = (
        format_duration(((now or datetime.now(tz=UTC)) - active_since).total_seconds())
        if active_since
        else "unknown"
    )

    return ServiceHealth(
        active_state=active_state,
        uptime=uptime,
        pid=values.get("MainPID") or "unknown",
        restarts=str(restarts) if restarts is not None else "unknown",
        memory_current_mb=format_mb(current_mb),
        memory_peak_mb=format_mb(peak_mb),
        color=service_color(active_state, restarts, current_mb, memory_cap_mb),
    )


def service_color(
    active_state: str,
    restarts: int | None,
    memory_current_mb: float | None,
    memory_cap_mb: float,
) -> str:
    """Return green, yellow, or red for service health."""

    if active_state != "active":
        return "red"
    if memory_current_mb is not None and memory_cap_mb > 0:
        usage = memory_current_mb / memory_cap_mb
        if usage > 0.95:
            return "red"
        if usage >= 0.80:
            return "yellow"
    if restarts and restarts > 0:
        return "yellow"
    return "green"


def heartbeat_summary(service_name: str, *, now: datetime) -> dict[str, str]:
    """Parse recent heartbeat journal lines."""

    output = run_command(
        ["journalctl", "-u", service_name, "--since", "15 minutes ago", "--no-pager"],
        timeout_seconds=10,
    )
    lines = [line for line in (output or "").splitlines() if "forward_indexer_heartbeat" in line]
    records = [parse_logfmt(line) for line in lines]
    latest = records[-1] if records else {}
    latest_ts = parse_iso_timestamp(str(latest.get("timestamp", "")))
    age = (now - latest_ts).total_seconds() if latest_ts else None
    snapshot_rates: list[float] = []
    for record in records:
        rate = parse_float(record.get("snapshots_per_second"))
        if rate is not None:
            snapshot_rates.append(rate)

    return {
        "latest_timestamp": latest_ts.isoformat() if latest_ts else "unknown",
        "age_seconds": format_number(age, decimals=0),
        "current_snapshots_per_second": str(latest.get("snapshots_per_second", "unknown")),
        "avg_snapshots_per_second": format_number(
            sum(snapshot_rates) / len(snapshot_rates) if snapshot_rates else None
        ),
        "markets_tracked": str(latest.get("markets_tracked", "unknown")),
        "websocket_connections": str(latest.get("websocket_connections", "unknown")),
        "errors_since_last": str(latest.get("errors_since_last_heartbeat", "unknown")),
        "dedupe_keys_retained": str(latest.get("dedupe_keys_retained", "unknown")),
    }


def capture_rate_summary(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    now: datetime,
) -> dict[str, str]:
    """Return rendered capture counts for snapshots and trades."""

    return {
        "snapshot_html": table_to_html(
            capture_counts(con, data_dir, "order_book_snapshots", now, "timestamp_utc")
        ),
        "trade_html": table_to_html(
            capture_counts(con, data_dir, "trade_events", now, "timestamp_utc")
        ),
    }


def capture_counts(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    table: str,
    now: datetime,
    timestamp_column: str,
) -> list[dict[str, Any]]:
    """Count records in recent and prior windows by venue."""

    if not table_has_parquet(data_dir, table):
        return []

    rows: list[dict[str, Any]] = []
    path = parquet_glob(data_dir, table)
    for hours in WINDOWS:
        start = now - timedelta(hours=hours)
        previous_start = now - timedelta(hours=hours * 2)
        current = query_counts_by_venue(con, path, timestamp_column, start, now)
        previous = query_counts_by_venue(con, path, timestamp_column, previous_start, start)
        venues = sorted(set(current) | set(previous))
        for venue in venues:
            rows.append(
                {
                    "window": f"{hours}h",
                    "venue": venue,
                    "current": current.get(venue, 0),
                    "previous": previous.get(venue, 0),
                    "delta": current.get(venue, 0) - previous.get(venue, 0),
                }
            )
    return rows


def storage_summary(data_dir: Path, now: datetime) -> dict[str, str]:
    """Return storage usage and growth fields."""

    files = list(data_dir.rglob("*.parquet")) if data_dir.exists() else []
    table_rows = [
        {"table": table, "size_mb": round(path_size_mb(data_dir / table), 2)} for table in TABLES
    ]
    growth = storage_growth_mb_per_hour(files, now=now)
    disk = shutil.disk_usage(existing_parent(data_dir))
    free_mb = disk.free / (1024 * 1024)
    days_until_full = free_mb / (growth * 24) if growth > 0 else None

    return {
        "total_size_mb": str(round(path_size_mb(data_dir), 2)),
        "disk_free_gb": str(round(disk.free / (1024 * 1024 * 1024), 2)),
        "growth_mb_per_hour": str(round(growth, 4)),
        "days_until_full": format_number(days_until_full, decimals=1),
        "table_html": table_to_html(table_rows),
    }


def storage_growth_mb_per_hour(paths: list[Path], *, now: datetime) -> float:
    """Estimate growth from parquet files modified in the last 24 hours."""

    cutoff = now.timestamp() - 24 * 60 * 60
    recent_bytes = sum(path.stat().st_size for path in paths if path.stat().st_mtime >= cutoff)
    return recent_bytes / (1024 * 1024) / 24


def data_quality_summary(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    now: datetime,
) -> dict[str, str]:
    """Return rendered data quality checks."""

    return {
        "kalshi_html": table_to_html(kalshi_book_quality(con, data_dir, now)),
        "polymarket_html": table_to_html(polymarket_source_breakdown(con, data_dir, now)),
        "gap_html": table_to_html(snapshot_gap_rows(con, data_dir, now)),
    }


def kalshi_book_quality(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    now: datetime,
) -> list[dict[str, Any]]:
    """Compute Kalshi book-depth quality over 1h and 24h windows."""

    if not table_has_parquet(data_dir, "order_book_snapshots"):
        return []

    path = parquet_glob(data_dir, "order_book_snapshots")
    rows: list[dict[str, Any]] = []
    for hours in (1, 24):
        start = now - timedelta(hours=hours)
        sql = """
            SELECT
                avg(len(bid_levels)) AS avg_bid_levels,
                avg(len(ask_levels)) AS avg_ask_levels,
                avg(CASE WHEN top_bid IS NOT NULL THEN 1.0 ELSE 0.0 END) AS pct_with_top_bid
            FROM read_parquet(?)
            WHERE venue = 'kalshi' AND timestamp_utc >= ? AND timestamp_utc < ?
        """
        try:
            result = con.execute(sql, [path, start, now]).fetchone()
        except duckdb.Error:
            result = None
        rows.append(
            {
                "window": f"{hours}h",
                "avg_bid_levels": format_number(result[0] if result else None),
                "avg_ask_levels": format_number(result[1] if result else None),
                "pct_with_top_bid": format_percent(result[2] if result else None),
            }
        )
    return rows


def polymarket_source_breakdown(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    now: datetime,
) -> list[dict[str, Any]]:
    """Compute Polymarket websocket/rest source percentages over 24h."""

    if not table_has_parquet(data_dir, "order_book_snapshots"):
        return []

    path = parquet_glob(data_dir, "order_book_snapshots")
    start = now - timedelta(hours=24)
    sql = """
        SELECT snapshot_source, count(*) AS n
        FROM read_parquet(?)
        WHERE venue = 'polymarket' AND timestamp_utc >= ? AND timestamp_utc < ?
        GROUP BY snapshot_source
    """
    rows = con.execute(sql, [path, start, now]).fetchall()
    total = sum(row[1] for row in rows)
    return [
        {
            "source": row[0] or "unknown",
            "count": row[1],
            "percent": format_percent(row[1] / total if total else None),
        }
        for row in rows
    ]


def snapshot_gap_rows(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return recent 5-minute windows below half the median count per venue."""

    if not table_has_parquet(data_dir, "order_book_snapshots"):
        return []

    path = parquet_glob(data_dir, "order_book_snapshots")
    start = now - timedelta(hours=24)
    sql = """
        SELECT
            venue,
            floor(epoch_ms(timestamp_utc) / 300000) * 300000 AS bucket_ms,
            count(*) AS snapshot_count
        FROM read_parquet(?)
        WHERE timestamp_utc >= ? AND timestamp_utc < ?
        GROUP BY venue, bucket_ms
        ORDER BY venue, bucket_ms
    """
    rows = [
        {"venue": row[0], "bucket_ms": int(row[1]), "snapshot_count": int(row[2])}
        for row in con.execute(sql, [path, start, now]).fetchall()
    ]
    gaps = detect_snapshot_gaps(rows)
    return [
        {
            "venue": gap["venue"],
            "window_start_utc": datetime.fromtimestamp(gap["bucket_ms"] / 1000, tz=UTC).isoformat(),
            "snapshot_count": gap["snapshot_count"],
            "venue_median": gap["median"],
        }
        for gap in gaps[:50]
    ]


def detect_snapshot_gaps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect bucket counts below half of a venue's median bucket count."""

    counts_by_venue: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        counts_by_venue[str(row["venue"])].append(int(row["snapshot_count"]))

    medians = {
        venue: median(counts)
        for venue, counts in counts_by_venue.items()
        if counts and median(counts) > 0
    }
    gaps: list[dict[str, Any]] = []
    for row in rows:
        venue = str(row["venue"])
        venue_median = medians.get(venue)
        if venue_median is None:
            continue
        count = int(row["snapshot_count"])
        if count < venue_median * 0.5:
            gaps.append({**row, "median": venue_median})
    return gaps


def error_log_summary(service_name: str) -> dict[str, str]:
    """Return recent error lines and known error-event counts."""

    output = run_command(
        ["journalctl", "-u", service_name, "--since", "24 hours ago", "--no-pager"],
        timeout_seconds=10,
    )
    lines = (output or "").splitlines()
    error_pattern = re.compile(r"error|exception|traceback", re.IGNORECASE)
    error_lines = [line for line in lines if error_pattern.search(line)][-20:]
    gamma_retries = sum("polymarket_gamma_retry" in line for line in lines)
    reconnects = sum(
        "ws_reconnect" in line or "websocket reconnect" in line.lower() for line in lines
    )
    return {
        "recent_errors": "\n".join(error_lines) if error_lines else "No recent error lines.",
        "gamma_retries_24h": str(gamma_retries),
        "websocket_reconnects_24h": str(reconnects),
    }


def query_counts_by_venue(
    con: duckdb.DuckDBPyConnection,
    path: str,
    timestamp_column: str,
    start: datetime,
    end: datetime,
) -> dict[str, int]:
    """Return count by venue for a bounded timestamp window."""

    sql = f"""
        SELECT venue, count(*) AS n
        FROM read_parquet(?)
        WHERE {timestamp_column} >= ? AND {timestamp_column} < ?
        GROUP BY venue
    """
    return {row[0]: int(row[1]) for row in con.execute(sql, [path, start, end]).fetchall()}


def run_command(args: list[str], *, timeout_seconds: int = 5) -> str | None:
    """Run a local command, returning stdout or None on failure."""

    try:
        result = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def parse_systemctl_show(output: str) -> dict[str, str]:
    """Parse `systemctl show` key-value output."""

    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def parse_logfmt(line: str) -> dict[str, str]:
    """Parse simple unquoted key=value log fields."""

    return {match.group(1): match.group(2) for match in re.finditer(r"(\w+)=([^\s]+)", line)}


def parse_systemd_timestamp(value: str | None) -> datetime | None:
    """Parse a common `systemctl show` timestamp."""

    if not value or value == "n/a":
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_iso_timestamp(value: str) -> datetime | None:
    """Parse ISO timestamps from structured logs."""

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_int(value: object) -> int | None:
    """Parse int-like values, treating systemd infinity values as missing."""

    if value in (None, "", "[not set]", "infinity"):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def parse_float(value: object) -> float | None:
    """Parse float-like values."""

    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def bytes_to_mb(value: int | None) -> float | None:
    """Convert bytes to megabytes."""

    return None if value is None else value / (1024 * 1024)


def format_mb(value: float | None) -> str:
    """Format megabytes."""

    return "unknown" if value is None else f"{value:.2f} MB"


def format_number(value: float | int | None, *, decimals: int = 2) -> str:
    """Format nullable numeric values."""

    if value is None:
        return "unknown"
    return f"{float(value):.{decimals}f}"


def format_percent(value: float | int | None) -> str:
    """Format nullable ratios as percentages."""

    if value is None:
        return "unknown"
    return f"{float(value) * 100:.2f}%"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds."""

    seconds_int = max(0, int(seconds))
    days, remainder = divmod(seconds_int, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def table_has_parquet(data_dir: Path, table: str) -> bool:
    """Return whether a table directory has parquet files."""

    table_dir = data_dir / table
    return table_dir.exists() and any(table_dir.rglob("*.parquet"))


def parquet_glob(data_dir: Path, table: str) -> str:
    """Return a DuckDB glob for one table."""

    return str(data_dir / table / "**" / "*.parquet")


def path_size_mb(path: Path) -> float:
    """Return recursive path size in MB."""

    if not path.exists():
        return 0.0
    if path.is_file():
        return path.stat().st_size / (1024 * 1024)
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file()) / (1024 * 1024)


def existing_parent(path: Path) -> Path:
    """Return the nearest existing parent for disk usage checks."""

    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def table_to_html(rows: list[dict[str, Any]]) -> str:
    """Render a list of dicts as an HTML table."""

    if not rows:
        return '<p class="muted">No data available.</p>'
    headers = list(rows[0].keys())
    header_html = "".join(f"<th>{escape_html(str(header))}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{escape_html(str(row.get(header, '')))}</td>" for header in headers)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><tr>{header_html}</tr>{''.join(body_rows)}</table>"


def escape_html(value: str) -> str:
    """Escape minimal HTML-sensitive characters."""

    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def write_atomic(html: str, output: Path) -> None:
    """Write HTML atomically through a temporary file."""

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = Path("/tmp") / f"{output.name}.tmp"
    temp_path.write_text(html, encoding="utf-8")
    os.replace(temp_path, output)


if __name__ == "__main__":
    raise SystemExit(main())
