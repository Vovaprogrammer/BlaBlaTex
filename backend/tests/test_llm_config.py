"""Настройки LLM: смена провайдера через окружение, валидация и сокрытие ключей."""

import json
import os
from decimal import Decimal

import pytest
import structlog
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture
def llm_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Только синтетические настройки: личные .env не читаются."""
    secret = "-".join(("synthetic", "provider", "credential"))
    model = {"name": "test-model", "input_price": "0.15", "output_price": "0.6"}
    provider = {
        "base_url": "https://primary.example.invalid/v1",
        "api_key": secret,
        "models": dict.fromkeys(("main", "fast", "vision"), model),
    }
    monkeypatch.setenv("LLM_PROVIDERS", json.dumps({"primary": provider, "backup": provider}))
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "primary")
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)
    return secret


def test_no_llm_configuration_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_PROVIDERS", "LLM_DEFAULT_PROVIDER", "LLM_FALLBACK_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    assert Settings(_env_file=None).llm_providers == {}


def test_provider_selection_and_prices_from_env(
    llm_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "backup")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "primary")
    settings = Settings(_env_file=None)
    assert settings.llm_default_provider == "backup"
    assert settings.llm_fallback_provider == "primary"
    provider = settings.llm_providers["backup"]
    assert provider.api_key.get_secret_value() == llm_env
    assert provider.models["main"].input_price == Decimal("0.15")
    assert provider.timeout == 30


@pytest.mark.parametrize(
    ("variable", "value"),
    [("LLM_DEFAULT_PROVIDER", "missing"), ("LLM_FALLBACK_PROVIDER", "primary")],
)
def test_invalid_selection(
    llm_env: str, monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "change",
    [
        {"timeout": 0},
        {"timeout": float("inf")},
        {"base_url": "https://user:password@example.invalid/v1"},
        {"base_url": "https://example.invalid/v1?token=synthetic"},
        {"models": {"main": {"name": "m", "input_price": -1, "output_price": 0}}},
        {"models": {}},
    ],
)
def test_invalid_provider_hides_input(
    llm_env: str, monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    providers = json.loads(os.environ["LLM_PROVIDERS"])
    providers["primary"].update(change)
    monkeypatch.setenv("LLM_PROVIDERS", json.dumps(providers))
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)
    assert llm_env not in str(error.value)


def test_keys_hidden_in_repr_json_and_logs(
    llm_env: str, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None)
    provider = settings.llm_providers["primary"]
    structlog.get_logger().info("settings", settings=settings, provider=provider)
    output = capsys.readouterr().out
    assert llm_env not in output + repr(settings) + repr(provider) + settings.model_dump_json()
