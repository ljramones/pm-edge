"""Console and optional webhook alerts for live paper trading."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from core.config import Settings, get_settings
from monitoring.telegram_alerts import TelegramMessage, TelegramNotifier
from utils.logging import get_logger

logger = get_logger(__name__)


class AlertConfig(BaseModel):
    """Notification settings for paper-trading alerts."""

    model_config = ConfigDict(frozen=True)

    console_enabled: bool = True
    generic_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None


class AlertManager:
    """Send important live-paper events to console and optional webhooks."""

    def __init__(
        self,
        config: AlertConfig | None = None,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        telegram_notifier: TelegramNotifier | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config = config or self._config_from_settings(self.settings)
        self.http_client = http_client or httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds
        )
        self.telegram_notifier = telegram_notifier or TelegramNotifier(
            settings=self.settings, http_client=self.http_client
        )
        self._owns_http_client = http_client is None

    async def close(self) -> None:
        """Close owned network resources."""

        if self._owns_http_client:
            await self.http_client.aclose()

    async def send(
        self, title: str, message: str, *, payload: dict[str, Any] | None = None
    ) -> None:
        """Send one alert through all configured channels."""

        if self.config.console_enabled:
            logger.warning(
                "paper_trader_alert", title=title, message=message, payload=payload or {}
            )

        await self._post_json(self.config.generic_webhook_url, {"title": title, "message": message})
        if self.config.discord_webhook_url:
            await self._post_json(
                self.config.discord_webhook_url,
                {"content": f"**{title}**\n{message}"},
            )
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
            await self._post_json(
                url,
                {"chat_id": self.config.telegram_chat_id, "text": f"{title}\n{message}"},
            )
        await self.telegram_notifier.send(TelegramMessage(text=f"<b>{title}</b>\n{message}"))

    async def _post_json(self, url: str | None, payload: dict[str, Any]) -> None:
        if not url:
            return
        try:
            response = await self.http_client.post(url, json=payload)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("paper_trader_alert_failed", url=url, error=str(exc))

    def _config_from_settings(self, settings: Settings) -> AlertConfig:
        return AlertConfig(
            generic_webhook_url=(
                settings.paper_trader_alert_webhook_url.get_secret_value()
                if settings.paper_trader_alert_webhook_url
                else None
            ),
            telegram_bot_token=None,
            telegram_chat_id=None,
            discord_webhook_url=(
                settings.paper_trader_discord_webhook_url.get_secret_value()
                if settings.paper_trader_discord_webhook_url
                else None
            ),
        )
