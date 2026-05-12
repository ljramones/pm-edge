from __future__ import annotations

import pytest

from core.config import Settings
from monitoring.telegram_alerts import TelegramNotifier


@pytest.mark.asyncio
async def test_telegram_notifier_disabled_is_noop() -> None:
    notifier = TelegramNotifier(settings=Settings(telegram_enabled=False))

    sent = await notifier.risk_alert("Risk", "Disabled")
    await notifier.close()

    assert sent is False
