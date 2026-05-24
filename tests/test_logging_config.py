"""Tests for httpx/httpcore log-noise suppression in configure_logging."""

from __future__ import annotations

import logging

import pytest

import utils.logging as logging_module
from core.config import Settings
from data.resolution_watcher.settings import ResolutionWatcherSettings
from utils.logging import _coerce_log_level, configure_logging


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("WARNING", logging.WARNING),
        ("warning", logging.WARNING),
        ("  info  ", logging.INFO),
        ("DEBUG", logging.DEBUG),
        ("ERROR", logging.ERROR),
        ("NOTALEVEL", None),
        ("", None),
    ],
)
def test_coerce_log_level(value: str, expected: int | None) -> None:
    assert _coerce_log_level(value) == expected


def test_default_silences_httpx_at_warning() -> None:
    """Requirement 1: httpx/httpcore default to WARNING after configuration."""

    configure_logging()

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_structured_loggers_unaffected() -> None:
    """Requirement 2: only httpx/httpcore are narrowed; INFO logging is intact."""

    configure_logging(level="INFO")

    # The root level (and therefore generic/structured diagnostic logging that
    # flows at INFO) is untouched by the httpx/httpcore suppression.
    assert logging.getLogger().level == logging.INFO
    # A non-httpx application logger still reports an effective level of INFO.
    app_logger = logging.getLogger("data.forward_indexer.runner")
    assert app_logger.getEffectiveLevel() == logging.INFO
    assert app_logger.isEnabledFor(logging.INFO)
    # httpx, by contrast, no longer emits at INFO.
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)


def test_env_override_restores_verbose_request_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement 3: PM_EDGE_HTTP_LOG_LEVEL=INFO restores per-request logging."""

    monkeypatch.setenv("PM_EDGE_HTTP_LOG_LEVEL", "INFO")

    # Forward indexer settings (global Settings, PM_EDGE_ prefix).
    forward_settings = Settings()
    assert forward_settings.http_log_level == "INFO"

    # Resolution watcher settings read the same global env var via alias.
    watcher_settings = ResolutionWatcherSettings()
    assert watcher_settings.http_log_level == "INFO"

    configure_logging(http_log_level=forward_settings.http_log_level)
    assert logging.getLogger("httpx").level == logging.INFO
    assert logging.getLogger("httpcore").level == logging.INFO
    assert logging.getLogger("httpx").isEnabledFor(logging.INFO)


def test_invalid_level_falls_back_to_warning_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement 4: an invalid level falls back to WARNING and logs a warning."""

    warnings: list[str] = []
    monkeypatch.setattr(
        logging_module.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )

    configure_logging(http_log_level="NOTALEVEL")

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert warnings, "expected a defensive warning for the invalid level"


def test_resolution_watcher_specific_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watcher-scoped env var still works for service-specific tuning."""

    monkeypatch.delenv("PM_EDGE_HTTP_LOG_LEVEL", raising=False)
    monkeypatch.setenv("PM_EDGE_RESOLUTION_WATCHER_HTTP_LOG_LEVEL", "DEBUG")

    settings = ResolutionWatcherSettings()
    assert settings.http_log_level == "DEBUG"
