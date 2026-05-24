"""Resolution watcher settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ResolutionWatcherSettings(BaseSettings):
    """Environment-driven runtime settings for the resolution watcher."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PM_EDGE_RESOLUTION_WATCHER_",
        extra="ignore",
        populate_by_name=True,
    )

    source_dir: Path = Path("data/raw/forward_index")
    output_dir: Path = Path("data/raw/resolved_market_outcomes")
    poll_cadence_seconds: int = Field(default=300, ge=1)
    polymarket_base_url: str = "https://clob.polymarket.com"
    kalshi_base_url: str = "https://external-api.kalshi.com/trade-api/v2"
    venues_enabled: list[str] = ["polymarket", "kalshi"]
    http_timeout_seconds: int = Field(default=20, ge=1)
    retry_attempts: int = Field(default=3, ge=1)
    heartbeat_interval_seconds: int = Field(default=60, ge=1)
    metadata_lookback_days: int = Field(default=7, ge=1)
    disappeared_lookback_hours: int = Field(default=24, ge=1)
    disappeared_max_checks_per_cycle: int = Field(default=50, ge=1)
    lag_tolerance_seconds: int = Field(default=5, ge=0)
    api_concurrency_limit: int = Field(
        default=10,
        ge=1,
        validation_alias=AliasChoices(
            "PM_EDGE_API_CONCURRENCY_LIMIT",
            "PM_EDGE_RESOLUTION_WATCHER_API_CONCURRENCY_LIMIT",
        ),
    )
    dry_run: bool = False
    http_log_level: str = Field(
        default="WARNING",
        validation_alias=AliasChoices(
            "PM_EDGE_HTTP_LOG_LEVEL",
            "PM_EDGE_RESOLUTION_WATCHER_HTTP_LOG_LEVEL",
        ),
    )
