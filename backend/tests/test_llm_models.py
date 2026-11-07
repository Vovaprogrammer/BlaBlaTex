"""Фабрика и переключение моделей: только тестовые модели, сеть запрещена."""

from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from pydantic_ai import Agent, models
from pydantic_ai.exceptions import ModelHTTPError, ModelRequestTimeout, ModelTimeoutError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel as PydanticTestModel

from app.core.config import LLMModelSettings, LLMProviderSettings, ModelRole, Settings
from app.modules.agent import models as factory


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Settings:
    providers = {
        name: LLMProviderSettings(
            base_url=f"https://{name}.example.invalid/v1",
            api_key=SecretStr(f"synthetic-{name}"),
            models={
                role: LLMModelSettings(name=f"{name}-{role}", input_price=0, output_price=0)
                for role in ("main", "fast", "vision")
            },
            timeout=7,
        )
        for name in ("primary", "backup")
    }
    settings = Settings(
        _env_file=None,
        llm_providers=providers,
        llm_default_provider="primary",
        llm_fallback_provider="backup",
    )
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    return settings


@pytest.mark.parametrize("role", ["main", "fast", "vision"])
async def test_factory_selects_roles_and_limits(configured: Settings, role: ModelRole) -> None:
    async with factory.get_model(role) as model:
        assert isinstance(model, FallbackModel)
        for candidate, name in zip(model.models, ("primary", "backup"), strict=True):
            assert candidate.model_name == f"{name}-{role}"
            assert candidate.base_url == f"https://{name}.example.invalid/v1/"
            assert candidate.settings == {"timeout": 7, "request_timeout": 7, "max_retries": 0}
            assert candidate.provider.client.api_key == f"synthetic-{name}"
            assert f"synthetic-{name}" not in repr(model)
    assert all(candidate.provider.client.is_closed() for candidate in model.models)


async def test_user_key_is_isolated_and_service_key_unchanged(configured: Settings) -> None:
    async with factory.get_model("main", SecretStr("synthetic-user")) as model:
        assert not isinstance(model, FallbackModel)
        assert model.provider.client.api_key == "synthetic-user"
        assert "synthetic-user" not in repr(model)
    assert configured.llm_providers["primary"].api_key.get_secret_value() == "synthetic-primary"
    configured.llm_fallback_provider = None
    async with factory.get_model("main") as model:
        assert model.provider.client.api_key == "synthetic-primary"


@pytest.mark.parametrize("missing", ["provider", "key"])
def test_missing_configuration_is_clear(configured: Settings, missing: str) -> None:
    if missing == "provider":
        configured.llm_default_provider = None
    else:
        configured.llm_providers["primary"].api_key = SecretStr("")
    with pytest.raises(ValueError, match="LLM"):
        factory.get_model("main")


@pytest.mark.parametrize(
    ("error", "fallback"),
    [(ModelHTTPError(code, "primary"), code >= 500) for code in (400, 401, 403, 429, 500, 503, 599)]
    + [(ModelTimeoutError("primary", "таймаут"), True), (ModelRequestTimeout("primary", 7), True)],
)
@pytest.mark.parametrize("stream", [False, True])
async def test_fallback_policy(
    configured: Settings,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    fallback: bool,
    stream: bool,
) -> None:
    def fail(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise error

    async def fail_stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        raise error
        yield ""  # Делает функцию асинхронным генератором, до вывода дело не доходит.

    backup = PydanticTestModel(custom_output_text="Ответ резервной модели")

    def build(provider: LLMProviderSettings, role: ModelRole, key: SecretStr) -> Model:
        return (
            FunctionModel(fail, stream_function=fail_stream)
            if provider is configured.llm_providers["primary"]
            else backup
        )

    monkeypatch.setattr(factory, "_provider_model", build)

    async def run() -> str:
        async with Agent(factory.get_model("main")) as agent:
            if stream:
                async with agent.run_stream("Проверка переключения") as result:
                    return await result.get_output()
            return (await agent.run("Проверка переключения")).output

    if fallback:
        assert await run() == "Ответ резервной модели"
    else:
        with pytest.raises(type(error)):
            await run()
        assert backup.last_model_request_parameters is None
