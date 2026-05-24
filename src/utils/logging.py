"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from loguru import logger


class InterceptHandler(logging.Handler):
    """Route stdlib logging records through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def _coerce_log_level(name: str) -> int | None:
    """Return the numeric logging level for ``name``, or ``None`` if invalid."""

    return logging.getLevelNamesMapping().get(name.strip().upper())


def configure_logging(
    *,
    level: str = "INFO",
    json_logs: bool = False,
    http_log_level: str = "WARNING",
) -> None:
    """Configure loguru and structlog with shared context support.

    ``http_log_level`` sets the level of the ``httpx`` and ``httpcore`` stdlib
    loggers. It defaults to ``WARNING`` so per-request ``HTTP Request`` INFO
    lines do not flood the journal, while failed/non-2xx requests still log.
    An unrecognised value falls back to ``WARNING`` with a logged warning.
    """

    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        serialize=json_logs,
        backtrace=False,
        diagnose=False,
        enqueue=True,
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=level.upper(), force=True)

    resolved_http_level = _coerce_log_level(http_log_level)
    if resolved_http_level is None:
        logger.warning("Invalid http_log_level {!r}; falling back to WARNING", http_log_level)
        resolved_http_level = logging.WARNING
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(resolved_http_level)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(structlog.processors.JSONRenderer() if json_logs else _logfmt_renderer)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def bind_context(**kwargs: Any) -> None:
    """Bind request, strategy, or run metadata to subsequent logs."""

    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound structured logging context."""

    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a context-aware structured logger."""

    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def _logfmt_renderer(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> str:
    parts = []
    event = event_dict.pop("event", None)
    if event:
        parts.append(str(event))
    parts.extend(f"{key}={value}" for key, value in sorted(event_dict.items()))
    return " ".join(parts)
