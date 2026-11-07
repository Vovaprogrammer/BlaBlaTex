"""Модели ролей из настроек; создание не вызывает провайдера."""

from pydantic import SecretStr
from pydantic_ai.exceptions import ModelHTTPError, ModelRequestTimeout, ModelTimeoutError
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import LLMProviderSettings, ModelRole, get_settings


def _should_fallback(error: Exception) -> bool:
    """Ошибки запроса и ключа не повод обращаться к другому провайдеру."""
    return isinstance(error, (ModelTimeoutError, ModelRequestTimeout)) or (
        isinstance(error, ModelHTTPError) and 500 <= error.status_code < 600
    )


def _provider_model(provider: LLMProviderSettings, role: ModelRole, key: SecretStr) -> Model:
    if not key.get_secret_value().strip():
        raise ValueError("Для выбранного LLM-провайдера не задан API-ключ")
    return OpenAIChatModel(
        provider.models[role].name,
        provider=OpenAIProvider(base_url=str(provider.base_url), api_key=key.get_secret_value()),
        # Без повторов внутри SDK: после 5xx или таймаута сразу пробуем резерв.
        settings={
            "timeout": provider.timeout,
            "request_timeout": provider.timeout,
            "max_retries": 0,
        },
    )


def get_model(role: ModelRole, user_key: SecretStr | None = None) -> Model:
    """Свежая модель для прогона; async with Agent(model) закрывает HTTP-клиенты.

    Пользовательский ключ относится только к основному провайдеру. С ним резерв
    отключён: чужой сервис не получает ключ, расход не переносится на ключ сервиса.
    """
    settings = get_settings()
    if settings.llm_default_provider is None:
        raise ValueError("LLM не настроен: укажите LLM_PROVIDERS и LLM_DEFAULT_PROVIDER")
    primary = settings.llm_providers[settings.llm_default_provider]
    model = _provider_model(primary, role, user_key if user_key is not None else primary.api_key)
    if user_key is not None or settings.llm_fallback_provider is None:
        return model
    backup = settings.llm_providers[settings.llm_fallback_provider]
    return FallbackModel(
        model, _provider_model(backup, role, backup.api_key), fallback_on=_should_fallback
    )
