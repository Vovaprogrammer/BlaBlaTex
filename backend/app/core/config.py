"""Настройки приложения из переменных окружения и файлов .env."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py → папка backend/.
BACKEND_DIR = Path(__file__).resolve().parents[2]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _upper(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


class Settings(BaseSettings):
    """Все настройки сервиса. Модули читают их только через get_settings()."""

    model_config = SettingsConfigDict(
        # Общий .env в корне репозитория (его же читает docker compose), затем backend/.env.
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        # В .env лежат переменные compose и других сервисов — бэкенду они не нужны.
        extra="ignore",
        # Пустое значение (как в .env.example) означает «взять значение по умолчанию».
        env_ignore_empty=True,
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: Annotated[LogLevel, BeforeValidator(_upper)] = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
