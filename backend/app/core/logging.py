"""Настройка structlog: читаемый вывод в dev, JSON в остальных окружениях."""

import structlog
from structlog.typing import Processor

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Настраивает structlog при создании приложения."""
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if settings.app_env == "dev":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors += [structlog.processors.dict_tracebacks, structlog.processors.JSONRenderer()]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
    )
