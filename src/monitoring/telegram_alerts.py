"""Optional Telegram notifications for live and research workflows."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from core.config import Settings, get_settings
from core.models import utc_now
from utils.logging import get_logger

logger = get_logger(__name__)

try:  # Optional runtime dependency; HTTP fallback below keeps local tests lightweight.
    from aiogram import Bot as AiogramBot
except ImportError:  # pragma: no cover - exercised when aiogram is not installed.
    AiogramBot = None  # type: ignore[assignment]


class TelegramButton(BaseModel):
    """Inline Telegram button payload."""

    text: str
    callback_data: str


class TelegramMessage(BaseModel):
    """Rendered Telegram message with optional inline buttons."""

    model_config = ConfigDict(frozen=True)

    text: str
    buttons: list[TelegramButton] = Field(default_factory=list)
    parse_mode: str | None = "HTML"


class TelegramNotifier:
    """Async Telegram notifier with rate limiting and graceful no-op fallback."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        enabled: bool | None = None,
        bot_token: str | None = None,
        chat_id: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.enabled = self.settings.telegram_enabled if enabled is None else enabled
        self.bot_token = bot_token or _secret_value(self.settings.telegram_bot_token)
        self.chat_id = chat_id or self.settings.telegram_chat_id
        self.rate_limit_seconds = self.settings.telegram_rate_limit_seconds
        self.http_client = http_client or httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds
        )
        self._owns_http_client = http_client is None
        self._last_sent_at: float | None = None

    @property
    def configured(self) -> bool:
        """Return whether Telegram can send messages."""

        return bool(self.enabled and self.bot_token and self.chat_id)

    async def close(self) -> None:
        """Close owned network resources."""

        if self._owns_http_client:
            await self.http_client.aclose()

    async def send(self, message: TelegramMessage) -> bool:
        """Send one message. Returns False when disabled or failed."""

        if not self.configured:
            logger.info("telegram_notifier_disabled")
            return False
        await self._rate_limit()
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": message.text,
            "disable_web_page_preview": True,
        }
        if message.parse_mode:
            payload["parse_mode"] = message.parse_mode
        if message.buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {"text": button.text, "callback_data": button.callback_data}
                        for button in message.buttons
                    ]
                ]
            }
        try:
            response = await self.http_client.post(self._telegram_url("sendMessage"), json=payload)
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("telegram_send_failed", error=str(exc))
            return False

    async def liquidity_opportunity(
        self,
        *,
        market_id: str,
        spread: float,
        incentive: float,
        edge: float,
        link: str | None = None,
    ) -> bool:
        """Alert on a liquidity-providing opportunity."""

        text = (
            "<b>Liquidity opportunity</b>\n"
            f"Market: <code>{market_id}</code>\n"
            f"Spread: {spread:.2%}\nIncentive: {incentive:.2f}\nEdge: {edge:.2%}"
        )
        if link:
            text += f"\nLink: {link}"
        return await self.send(
            TelegramMessage(
                text=text,
                buttons=[
                    TelegramButton(text="Approve", callback_data=f"approve:{market_id}"),
                    TelegramButton(text="Pause", callback_data="pause"),
                    TelegramButton(text="Status", callback_data="status"),
                ],
            )
        )

    async def high_edge_review(
        self,
        *,
        market_id: str,
        edge: float,
        confidence: float,
        reasoning: list[str] | None = None,
    ) -> bool:
        """Alert on a high-edge directional paper bet requiring review."""

        details = "\n".join(reasoning or [])[:900]
        return await self.send(
            TelegramMessage(
                text=(
                    "<b>High-edge review</b>\n"
                    f"Market: <code>{market_id}</code>\n"
                    f"Edge: {edge:.2%}\nConfidence: {confidence:.2%}\n{details}"
                ),
                buttons=[
                    TelegramButton(text="Approve", callback_data=f"approve:{market_id}"),
                    TelegramButton(text="Pause", callback_data="pause"),
                    TelegramButton(text="Status", callback_data="status"),
                ],
            )
        )

    async def risk_alert(self, title: str, message: str) -> bool:
        """Alert on degradation, risk, or operational issues."""

        return await self.send(TelegramMessage(text=f"<b>{title}</b>\n{message}"))

    async def high_fear_setup(
        self,
        *,
        market_id: str,
        fear_score: float,
        temperature: float,
        edge: float,
        link: str | None = None,
    ) -> bool:
        """Alert on a high-fear setup that survived routing."""

        text = (
            "<b>High-fear setup</b>\n"
            f"Market: <code>{market_id}</code>\n"
            f"Fear: {fear_score:.2f}\nTemperature: {temperature:.4f}\nEdge: {edge:.2%}"
        )
        if link:
            text += f"\nLink: {link}"
        return await self.send(
            TelegramMessage(
                text=text,
                buttons=[
                    TelegramButton(text="Approve", callback_data=f"approve:{market_id}"),
                    TelegramButton(text="Pause", callback_data="pause"),
                    TelegramButton(text="Status", callback_data="status"),
                ],
            )
        )

    async def daily_summary(
        self, metrics: dict[str, Any], *, as_of: datetime | None = None
    ) -> bool:
        """Send daily performance summary."""

        timestamp = as_of or utc_now()
        body = "\n".join(f"{key}: {value}" for key, value in sorted(metrics.items()))[:2500]
        return await self.send(
            TelegramMessage(text=f"<b>Daily summary</b> {timestamp.date().isoformat()}\n{body}")
        )

    async def _rate_limit(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._last_sent_at is not None:
            await asyncio.sleep(max(0.0, self.rate_limit_seconds - (now - self._last_sent_at)))
        self._last_sent_at = loop.time()

    def _telegram_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"


def _secret_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value.get_secret_value())
