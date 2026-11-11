"""Настройки LLM и шифрования для тестов своего ключа и квоты: провайдер-заглушка, ключи
Fernet и сохранение ключа студента без запроса к провайдеру."""

import uuid
from typing import Any

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import LLMProviderSettings, Settings
from app.modules.llm import service
from app.modules.llm.service import KeyVerdict

ENCRYPTION_KEY = Fernet.generate_key().decode()
OTHER_ENCRYPTION_KEY = Fernet.generate_key().decode()
PROVIDER = "openrouter"
BASE_URL = "https://llm.example.test/api/v1"
MAIN_MODEL = "main-model"
# Похож на настоящий ключ OpenRouter, но выдуман.
STUDENT_KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"


def _provider(base_url: str = BASE_URL) -> dict[str, Any]:
    # Any — JSON настройки провайдера, как в LLM_PROVIDERS.
    models = {
        role: {"name": f"{role}-model", "input_price": 1, "output_price": 2}
        for role in ("main", "fast", "vision")
    }
    return {"base_url": base_url, "api_key": "service-key", "models": models}


def llm_settings(**overrides: Any) -> Settings:
    """Настройки с основным и резервным провайдерами и шифрованием своих ключей."""
    # Any — поля Settings разных типов.
    options: dict[str, Any] = {
        "_env_file": None,
        "app_env": "test",
        "llm_providers": {PROVIDER: _provider(), "backup": _provider("https://backup.test/v1")},
        "llm_default_provider": PROVIDER,
        "app_encryption_key": SecretStr(ENCRYPTION_KEY),
        **overrides,
    }
    return Settings(**options)


async def accept(provider: LLMProviderSettings, key: SecretStr) -> KeyVerdict:
    """Проверка ключа без провайдера: любой ключ подходит."""
    return KeyVerdict.ACCEPTED


async def store_key(
    session: AsyncSession, user_id: uuid.UUID, settings: Settings, key: str = STUDENT_KEY
) -> None:
    """Студент сохранил свой ключ на сайте."""
    await service.save_key(session, user_id, SecretStr(key), settings, accept)
