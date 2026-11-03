"""Точки входа агента (architecture.md 9.4): ключ и текст студента не попадают в repr и логи."""

import asyncio
import uuid
from typing import cast

import structlog
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.modules.agent.contract import HistoryMessage, RunEvents, RunRequest
from app.modules.projects.tools import ProjectTools, ToolContext

KEY = "sk-user-secret-0123456789"
STUDENT_TEXT = "Мой вариант 7, ФИО Иванов"


def _request() -> RunRequest:
    context = ToolContext(
        project_id=uuid.uuid4(), user_id=uuid.uuid4(), actor="ai", changeset_id=uuid.uuid4()
    )
    return RunRequest(
        history=[HistoryMessage(role="user", text=STUDENT_TEXT)],
        context=context,
        # Инструменты и события в этих тестах не вызываются.
        tools=cast(ProjectTools, object()),
        events=cast(RunEvents, object()),
        cancel=asyncio.Event(),
        max_tokens=100_000,
        user_key=SecretStr(KEY),
    )


def test_run_request_hides_key_and_history() -> None:
    request = _request()
    for shown in (repr(request), str(request), repr(request.history[0])):
        assert KEY not in shown
        assert STUDENT_TEXT not in shown
    # Сами значения агенту доступны.
    assert request.user_key is not None
    assert request.user_key.get_secret_value() == KEY
    assert request.history[0].text == STUDENT_TEXT


def test_logged_run_request_hides_key_and_history() -> None:
    with capture_logs() as logs:
        structlog.get_logger().info("run_started", request=_request())
    rendered = repr(logs)
    assert KEY not in rendered
    assert STUDENT_TEXT not in rendered
