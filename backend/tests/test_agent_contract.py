"""Точки входа агента (architecture.md 9.4): ключ, текст студента и план не попадают в repr
и логи."""

import asyncio
import uuid
from dataclasses import replace
from decimal import Decimal
from typing import cast

import structlog
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.modules.agent.contract import (
    HistoryMessage,
    ModelUsage,
    PlanRequest,
    PlanResult,
    PlanTools,
    RunEvents,
    RunRequest,
)
from app.modules.plans.schemas import PlanSection, ReportPlan
from app.modules.projects.tools import ProjectTools, TemplateGuide, ToolContext

KEY = "sk-user-secret-0123456789"
STUDENT_TEXT = "Мой вариант 7, ФИО Иванов"


def _request() -> RunRequest:
    context = ToolContext(
        project_id=uuid.uuid4(), user_id=uuid.uuid4(), actor="ai", changeset_id=uuid.uuid4()
    )
    return RunRequest(
        run_id=uuid.uuid4(),
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


NOTE = "Студент не сделал задание 3"


def _plan() -> ReportPlan:
    section = PlanSection(section_id="goal", title="Цель работы", materials=[], note=NOTE)
    return ReportPlan(sections=[section], unassigned=[])


def _plan_request() -> PlanRequest:
    context = ToolContext(
        project_id=uuid.uuid4(), user_id=uuid.uuid4(), actor="ai", changeset_id=uuid.uuid4()
    )
    return PlanRequest(
        run_id=uuid.uuid4(),
        history=[HistoryMessage(role="user", text=STUDENT_TEXT)],
        guide=cast(TemplateGuide, object()),
        materials=[],
        context=context,
        tools=cast(PlanTools, object()),
        cancel=asyncio.Event(),
        max_tokens=100_000,
        user_key=SecretStr(KEY),
    )


def test_plan_request_and_result_hide_key_history_and_notes() -> None:
    usage = ModelUsage(model="stub", tokens_in=0, tokens_out=0, cost=Decimal(0))
    run_request = replace(_request(), plan=_plan())
    with capture_logs() as logs:
        structlog.get_logger().info(
            "plan_started",
            request=_plan_request(),
            run_request=run_request,
            result=PlanResult(status="done", plan=_plan(), usage=usage),
        )
    rendered = repr(logs)
    for secret in (KEY, STUDENT_TEXT, NOTE):
        assert secret not in rendered
    assert run_request.plan is not None
    assert run_request.plan.sections[0].note == NOTE
