"""Настройка structlog: читаемый вывод в dev, JSON в остальных окружениях."""

import structlog
from structlog.typing import Processor

from app.core.config import Settings

# Трейсбеки — без локальных переменных: в них бывают пароли, ключи и тексты пользователей.
# По умолчанию structlog и rich их показывают.
_dict_tracebacks = structlog.processors.ExceptionRenderer(
    structlog.processors.ExceptionDictTransformer(show_locals=False)
)
_console_tracebacks = (
    structlog.dev.RichTracebackFormatter(show_locals=False)
    if structlog.dev.rich is not None
    else structlog.dev.plain_traceback
)


def configure_logging(settings: Settings) -> None:
    """Настраивает structlog при создании приложения."""
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if settings.app_env == "dev":
        processors.append(structlog.dev.ConsoleRenderer(exception_formatter=_console_tracebacks))
    else:
        processors += [_dict_tracebacks, structlog.processors.JSONRenderer()]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
    )
