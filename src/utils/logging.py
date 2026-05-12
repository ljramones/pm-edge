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


def configure_logging(*, level: str = "INFO", json_logs: bool = False) -> None:
    """Configure loguru and structlog with shared context support."""

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
