"""Настройки приложения из переменных окружения и файлов .env."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from cryptography.fernet import Fernet
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

# backend/app/core/config.py → папка backend/.
BACKEND_DIR = Path(__file__).resolve().parents[2]
# Шаблоны отчётов в репозитории (architecture.md 7).
TEMPLATES_DIR = BACKEND_DIR.parent / "templates"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
ModelRole = Literal["main", "fast", "vision"]
TokenPrice = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class LLMModelSettings(BaseModel):
    """Модель и цены за миллион входных/выходных токенов в USD."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)

    name: str = Field(min_length=1)
    input_price: TokenPrice
    output_price: TokenPrice


class LLMProviderSettings(BaseModel):
    """OpenAI-совместимый провайдер; ключ не отображается в repr и JSON."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    base_url: AnyHttpUrl
    api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    models: dict[ModelRole, LLMModelSettings]
    timeout: float = Field(default=30, gt=0, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def plain_base_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("В base_url нельзя указывать авторизацию, query или fragment")
        return value

    @field_validator("models")
    @classmethod
    def all_roles(
        cls, value: dict[ModelRole, LLMModelSettings]
    ) -> dict[ModelRole, LLMModelSettings]:
        if set(value) != {"main", "fast", "vision"}:
            raise ValueError("Нужны модели для всех ролей: main, fast, vision")
        return value


def _upper(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


def _split_keys(value: SecretStr) -> list[str]:
    return [key.strip() for key in value.get_secret_value().split(",") if key.strip()]


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
        # Ошибка вложенного LLM_PROVIDERS не должна напечатать исходный JSON с ключами.
        hide_input_in_errors=True,
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

    # Папка хранилища файлов по sha256 (core/storage.py); в проде — volume Docker.
    storage_dir: Path = BACKEND_DIR / "data" / "storage"

    # Папка шаблонов (architecture.md 7): реестр читает её при старте приложения.
    templates_dir: Path = TEMPLATES_DIR

    # Компилятор (architecture.md 9.7). В dev бэкенд работает на хосте и ходит через
    # compiler-proxy на localhost — порт тот же, что у docker compose. Внутри compose
    # адрес задаётся явно: http://compiler:8080.
    compiler_url: AnyHttpUrl | None = None
    compiler_port: int = 8080

    # Redis — очередь задач воркера и события проектов (architecture.md 2, 9.3). Как
    # с компилятором: в dev бэкенд ходит на localhost:REDIS_PORT, внутри compose адрес
    # задаётся явно: redis://redis:6379/0.
    # В адресе бывает пароль, поэтому его нет в repr настроек.
    redis_url: Annotated[RedisDsn | None, Field(repr=False)] = None
    redis_port: int = 6379

    # Лимит токенов на один прогон агента, вход и выход вместе (RunRequest.max_tokens, 9.4).
    agent_run_max_tokens: PositiveInt = 200_000
    # Описывать скриншоты из materials/ vision-моделью (describe_image, 9.4). По умолчанию
    # выключено: каждое описание стоит денег.
    material_describe_images: bool = False

    # Шифрование своих ключей LLM студентов (architecture.md 5, 9.1): ключи Fernet через
    # запятую. Первым шифруется, расшифровывается любым — так ключ шифрования меняют, не теряя
    # сохранённые (app/scripts/rotate_llm_keys.py). Пусто — свой ключ сохранить нельзя.
    app_encryption_key: Annotated[SecretStr | None, Field(repr=False)] = None

    # Пустая конфигурация не мешает API и заглушке агента работать без LLM.
    llm_providers: dict[str, LLMProviderSettings] = Field(default_factory=dict, repr=False)
    llm_default_provider: str | None = None
    llm_fallback_provider: str | None = None

    @field_validator("app_encryption_key")
    @classmethod
    def fernet_keys(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        keys = _split_keys(value)
        if not keys:
            raise ValueError("APP_ENCRYPTION_KEY: нет ни одного ключа")
        for key in keys:
            try:
                Fernet(key)
            # Текст ошибки — без значения ключа.
            except ValueError:
                raise ValueError(
                    "APP_ENCRYPTION_KEY: каждый ключ — 32 байта в url-safe base64, "
                    "как от Fernet.generate_key()"
                ) from None
        return value

    @model_validator(mode="after")
    def configured_llm_providers(self) -> Self:
        if self.llm_providers and self.llm_default_provider is None:
            raise ValueError("Укажите LLM_DEFAULT_PROVIDER")
        for name in (self.llm_default_provider, self.llm_fallback_provider):
            if name is not None and name not in self.llm_providers:
                raise ValueError("Выбранный LLM-провайдер отсутствует в LLM_PROVIDERS")
        if self.llm_fallback_provider is not None:
            if self.llm_fallback_provider == self.llm_default_provider:
                raise ValueError("Основной и резервный LLM-провайдеры должны различаться")
        return self

    @property
    def encryption_keys(self) -> list[str]:
        """Ключи шифрования по порядку: первый шифрует, все расшифровывают."""
        return [] if self.app_encryption_key is None else _split_keys(self.app_encryption_key)

    @property
    def redis_base_url(self) -> str:
        """Адрес Redis: REDIS_URL или localhost:REDIS_PORT, база 0."""
        if self.redis_url is not None:
            return str(self.redis_url)
        return f"redis://localhost:{self.redis_port}/0"

    @property
    def compiler_base_url(self) -> str:
        """Адрес компилятора: COMPILER_URL или прокси на localhost:COMPILER_PORT."""
        if self.compiler_url is not None:
            return str(self.compiler_url)
        return f"http://localhost:{self.compiler_port}"

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
