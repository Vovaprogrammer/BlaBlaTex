"""Сценарная модель проходит настоящие инструменты без подключения к сети."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.agent import models, runner
from app.modules.agent.contract import HistoryMessage, RunRequest
from app.modules.projects.tools import ToolContext
from tests.fake_project_tools import FakeProjectTools, build_error, build_ok, latex_error
from tests.fake_run_events import FakeRunEvents


def test_scripted_mode_is_opt_in_and_only_for_test_environment() -> None:
    assert Settings(_env_file=None).llm_test_mode is None
    assert Settings(_env_file=None, app_env="test", llm_test_mode="scripted").llm_test_mode == (
        "scripted"
    )
    for app_env in ("dev", "local", "prod"):
        with pytest.raises(ValidationError, match="только при APP_ENV=test"):
            Settings(_env_file=None, app_env=app_env, llm_test_mode="scripted")


async def test_scripted_run_creates_edits_and_compiles_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, app_env="test", llm_test_mode="scripted")
    monkeypatch.setattr(models, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)

    async def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Запросы в сеть в тестовом режиме запрещены")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    tools = FakeProjectTools({"sections/progress.tex": "old"}, builds=[build_ok()])
    events = FakeRunEvents()
    request = RunRequest(
        uuid4(),
        [HistoryMessage(role="user", text="Сделай отчёт")],
        ToolContext(uuid4(), uuid4(), "ai", None),
        tools,
        events,
        asyncio.Event(),
        100_000,
    )

    result = await runner.run_agent(request)

    assert result.status == "done"
    assert result.text == "Тестовый сценарий выполнен, PDF собран."
    assert result.usage.model == "scripted-test"
    assert "Сценарий: готово." in (await tools.read_file("sections/scripted-test.tex")).text
    assert (
        "\\input{sections/scripted-test}" in (await tools.read_file("sections/progress.tex")).text
    )
    names = [event.data["tool"] for event in events.events if event.type == "run.tool_call"]
    assert names == ["write_file", "edit_file", "write_file", "compile"]


async def test_scripted_does_not_claim_success_when_build_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, app_env="test", llm_test_mode="scripted")
    monkeypatch.setattr(models, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    tools = FakeProjectTools(builds=[build_error(latex_error("synthetic error"))])
    request = RunRequest(
        uuid4(),
        [HistoryMessage(role="user", text="Собери")],
        ToolContext(uuid4(), uuid4(), "ai", None),
        tools,
        FakeRunEvents(),
        asyncio.Event(),
        100_000,
    )
    result = await runner.run_agent(request)
    assert result.text == "Тестовый сценарий выполнен, но PDF не собрался."


async def test_scripted_stops_if_tool_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, app_env="test", llm_test_mode="scripted")
    monkeypatch.setattr(models, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    tools = FakeProjectTools(builds=[build_ok()])
    tools.locked = True
    events = FakeRunEvents()
    request = RunRequest(
        uuid4(),
        [HistoryMessage(role="user", text="Собери")],
        ToolContext(uuid4(), uuid4(), "ai", None),
        tools,
        events,
        asyncio.Event(),
        100_000,
    )

    result = await runner.run_agent(request)

    assert result.text == "Тестовый сценарий остановлен: инструмент вернул ошибку."
    names = [event.data["tool"] for event in events.events if event.type == "run.tool_call"]
    assert names == ["write_file"]


def test_other_roles_do_not_fall_back_to_network(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, app_env="test", llm_test_mode="scripted")
    monkeypatch.setattr(models, "get_settings", lambda: settings)
    for role in ("fast", "vision"):
        with pytest.raises(ValueError, match="только роль main"):
            models.get_model(role)  # type: ignore[arg-type]
