"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    kalshi_api_key: SecretStr | None = None
    kalshi_api_secret: SecretStr | None = None
    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"

    news_api_key: SecretStr | None = None
    etherscan_api_key: SecretStr | None = None
    gdelt_base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"

    http_timeout_seconds: float = Field(default=20.0, ge=1.0)
    http_max_connections: int = Field(default=20, ge=1)
    retry_attempts: int = Field(default=3, ge=1)
    retry_min_seconds: float = Field(default=0.25, ge=0.0)
    retry_max_seconds: float = Field(default=4.0, ge=0.0)

    paper_trading: bool = True
    max_order_notional_usd: float = Field(default=100.0, gt=0)
    max_portfolio_notional_usd: float = Field(default=1_000.0, gt=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_live_trading_enabled(self) -> bool:
        """Return whether live trading is explicitly enabled."""

        return not self.paper_trading and self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
