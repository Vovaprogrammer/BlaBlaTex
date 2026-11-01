"""Логи structlog в JSON: сервис работает только в контейнере."""

import logging

import structlog


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Трейсбек без локальных переменных: в них бывают куски файлов проекта.
            structlog.processors.ExceptionRenderer(
                structlog.processors.ExceptionDictTransformer(show_locals=False)
            ),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
