"""Настройки приложения из переменных окружения и файлов .env."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, NonNegativeInt, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

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

    # Postgres: те же переменные, что у docker compose, — пароль не дублируется.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "blablatex"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "blablatex"
    db_pool_size: PositiveInt = 5
    db_max_overflow: NonNegativeInt = 10

    @property
    def database_url(self) -> URL:
        """Адрес Postgres для SQLAlchemy. URL.create сам экранирует спецсимволы в пароле."""
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value() or None,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
