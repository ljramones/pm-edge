"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from utils.paths import resolve_repo_path


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
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_chain_id: int = 137

    kalshi_api_key: SecretStr | None = None
    kalshi_api_secret: SecretStr | None = None
    kalshi_base_url: str = "https://external-api.kalshi.com/trade-api/v2"
    kalshi_request_delay_seconds: float = Field(default=0.2, ge=0.0)

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
    forward_indexer_output_dir: Path = Path("data/raw/forward_index")
    forward_indexer_emit_cadence_seconds: int = Field(default=15, ge=1)
    forward_indexer_discovery_cadence_seconds: float = Field(default=1800.0, ge=1)
    forward_indexer_book_depth_levels: int = Field(default=5, ge=1, le=50)
    forward_indexer_min_24h_volume_usd: float = Field(default=10_000.0, ge=0.0)
    forward_indexer_max_spread_cents: float = Field(default=10.0, ge=0.0)
    forward_indexer_max_last_trade_age_hours: float = Field(default=24.0, ge=0.0)
    forward_indexer_min_market_age_minutes: float = Field(default=30.0, ge=0.0)
    forward_indexer_min_time_to_close_hours: float = Field(default=2.0, ge=0.0)
    forward_indexer_max_memory_mb: float = Field(default=1024.0, gt=0)

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
            "forward_indexer_output_dir",
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
