"""Прогоны плана в воркере (architecture.md 8 «План отчёта», 9.4): прогон plan сохраняет план
вместе с итогом, ответ — текст и карточка плана, сбой и отмена план не трогают; прогон
report получает подтверждённый план в RunRequest.plan.

Прогон открывает свои сессии, поэтому тесты — на настоящих соединениях (фикстура live).
"""

import asyncio
import dataclasses
import uuid

import pytest
from sqlalchemy import update

from app.core.events import EventType, PlanUpdatedData
from app.modules.agent import plan_stub
from app.modules.agent.contract import PlanResult, RunRequest, RunResult
from app.modules.chat import runner
from app.modules.plans import service as plans_service
from app.modules.plans.models import ReportPlanRow
from app.modules.plans.schemas import NOTE_MAX_LENGTH, ReportPlan
from app.modules.projects import service as projects_service
from app.modules.projects.models import Project
from app.modules.templates import service as templates_service
from app.modules.templates.registry import Registry, load_templates
from app.modules.templates.schemas import TemplateSection
from tests.fake_events import FakeEvents
from tests.fake_make_plan import PLAN_USAGE, FakeMakePlan, plan_of, plan_request
from tests.fake_project_tools import DEFAULT_GUIDE, FakeMaterial, FakeProjectTools
from tests.helpers import TEMPLATE_FIXTURES, writer
from tests.live_builds import Live, new_project
from tests.live_runs import (
    FAST,
    execute,
    new_run,
    parts,
    reply_of,
    request_cancel,
    stored_run,
    usage_of,
    wait_status,
)

TASK = "materials/task.md"
CODE = "materials/main.py"
# Материалы ещё не разобраны: прогон их не ждёт.
NO_WAIT = dataclasses.replace(FAST, materials_wait_s=0)


@pytest.fixture
def templates() -> Registry:
    return load_templates(TEMPLATE_FIXTURES)


async def plan_run(live: Live) -> tuple[uuid.UUID, uuid.UUID]:
    """Проект test-lab (разделы goal и conclusion) с двумя материалами и прогон plan."""
    project_id = await new_project(live)
    async with live.sessionmaker() as session:
        for path, text in ((TASK, "Задание: вариант 7"), (CODE, "print(1)\n")):
            await projects_service.write_text_file(session, writer(), project_id, path, text)
    return await new_run(live, "Составь план отчёта", project_id, kind="plan")


async def stored_plan(live: Live, project_id: uuid.UUID) -> ReportPlanRow | None:
    async with live.sessionmaker() as session:
        return await session.get(ReportPlanRow, project_id)


async def test_plan_run_saves_draft_and_answers(live: Live, templates: Registry) -> None:
    project_id, run_id = await plan_run(live)
    # Модель вернула лишнее: чужой раздел, повтор раздела, несуществующий материал, повтор
    # материала и длинную заметку. Сохраняется план, приведённый к шаблону.
    planner = FakeMakePlan(
        PlanResult(
            status="done",
            plan=plan_of(
                ("conclusion", [CODE], "Вывод по замерам"),
                ("goal", [TASK, "materials/nope.py", TASK], "я" * (NOTE_MAX_LENGTH + 5)),
                ("intro", [CODE], ""),
                ("goal", [CODE], "повтор"),
                unassigned=[CODE],
            ),
            usage=PLAN_USAGE,
        )
    )
    events = FakeEvents()

    await execute(live, run_id, events, templates, timing=NO_WAIT, make_plan=planner)

    [request] = planner.requests
    assert [section.id for section in request.guide.sections] == ["goal", "conclusion"]
    assert [material.path for material in request.materials] == [CODE, TASK]
    assert request.history[-1].text == "Составь план отчёта"
    assert request.context.project_id == project_id
    assert request.max_tokens == 10_000
    # make_plan материалы только читает: записать файл через его инструменты нельзя.
    assert isinstance(request.tools, runner.PlanTools)
    assert not hasattr(request.tools, "write_file")
    row = await stored_plan(live, project_id)
    assert row is not None
    assert row.status == "draft"
    assert row.plan == {
        "sections": [
            {"section_id": "goal", "materials": [TASK], "note": "я" * NOTE_MAX_LENGTH},
            {"section_id": "conclusion", "materials": [CODE], "note": "Вывод по замерам"},
        ]
    }
    reply = await reply_of(live, project_id)
    assert reply.status == "done"
    assert parts(reply) == [
        {
            "type": "text",
            "text": "План отчёта готов. Разделов: 2, материалов вне плана: 0. Проверьте план, "
            "поправьте, если нужно, и нажмите «Подтвердить» — тогда ИИ напишет отчёт по нему.",
        },
        {"type": "plan"},
    ]
    run = await stored_run(live, run_id)
    assert (run.kind, run.model, run.tokens_in) == ("plan", "test-model", 300)
    assert await usage_of(live) == (300, 80, PLAN_USAGE.cost, 1)
    assert events.types == [
        EventType.PROJECT_LOCKED,
        EventType.RUN_STARTED,
        EventType.RUN_DELTA,
        EventType.PLAN_UPDATED,
        EventType.RUN_FINISHED,
        EventType.PROJECT_UNLOCKED,
    ]
    updated = events.published[3].data
    assert updated == PlanUpdatedData(status="draft", updated_at=row.updated_at)


async def test_stub_plan_puts_unknown_types_outside(live: Live, templates: Registry) -> None:
    # В test-lab нет разделов task и progress: заглушка всё оставляет вне плана.
    project_id, run_id = await plan_run(live)

    await execute(live, run_id, FakeEvents(), templates, timing=NO_WAIT)

    async with live.sessionmaker() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        out = await plans_service.get_plan(session, project, templates)
    assert [section.materials for section in out.plan.sections] == [[], []]
    assert out.plan.unassigned == [CODE, TASK]
    assert (await stored_run(live, run_id)).model == plan_stub.STUB_MODEL


async def test_failed_plan_keeps_previous_plan(live: Live, templates: Registry) -> None:
    project_id, run_id = await plan_run(live)
    async with live.sessionmaker() as session:
        previous = await plans_service.save_generated(
            session, project_id, plan_of(("goal", [TASK], "Прежний"))
        )
        await session.commit()
    planner = FakeMakePlan(
        PlanResult(status="failed", error="Модель сейчас недоступна.", usage=PLAN_USAGE)
    )
    events = FakeEvents()

    await execute(live, run_id, events, templates, timing=NO_WAIT, make_plan=planner)

    row = await stored_plan(live, project_id)
    assert row is not None
    assert (row.plan["sections"][0]["note"], row.updated_at) == ("Прежний", previous.updated_at)
    reply = await reply_of(live, project_id)
    assert reply.status == "failed"
    assert parts(reply) == [{"type": "error", "text": "Модель сейчас недоступна."}]
    assert EventType.PLAN_UPDATED not in events.types
    # Токены потрачены — расход записан.
    assert await usage_of(live) == (300, 80, PLAN_USAGE.cost, 1)


async def test_crashed_make_plan_fails_run(live: Live, templates: Registry) -> None:
    project_id, run_id = await plan_run(live)
    planner = FakeMakePlan(error=RuntimeError("сбой"))

    await execute(live, run_id, FakeEvents(), templates, timing=NO_WAIT, make_plan=planner)

    run = await stored_run(live, run_id)
    assert (run.status, run.error) == ("failed", runner.RUN_FAILED_MESSAGE)
    assert await stored_plan(live, project_id) is None


async def test_cancelled_plan_run_saves_nothing(live: Live, templates: Registry) -> None:
    project_id, run_id = await plan_run(live)
    planner = FakeMakePlan(wait_cancel=True)
    task = asyncio.create_task(
        execute(live, run_id, FakeEvents(), templates, timing=NO_WAIT, make_plan=planner)
    )
    await wait_status(live, run_id, "running")
    async with asyncio.timeout(5):
        while not planner.requests:  # noqa: ASYNC110
            await asyncio.sleep(0.01)

    await request_cancel(live, run_id)
    await task

    assert (await stored_run(live, run_id)).status == "cancelled"
    assert await stored_plan(live, project_id) is None


async def test_template_gone_fails_without_make_plan(live: Live, templates: Registry) -> None:
    project_id, run_id = await plan_run(live)
    async with live.sessionmaker() as session:
        await session.execute(
            update(Project).where(Project.id == project_id).values(template_slug="gone")
        )
        await session.commit()
    planner = FakeMakePlan()

    await execute(live, run_id, FakeEvents(), templates, timing=NO_WAIT, make_plan=planner)

    run = await stored_run(live, run_id)
    assert (run.status, run.error) == ("failed", templates_service.TEMPLATE_GONE_MESSAGE)
    # До модели прогон не дошёл — модели у него нет, как у прогона, отменённого в ожидании.
    assert run.model is None
    assert planner.requests == []


async def test_chat_run_does_not_make_plan(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    planner = FakeMakePlan()

    await execute(live, run_id, FakeEvents(), templates, timing=NO_WAIT, make_plan=planner)

    assert planner.requests == []
    assert await stored_plan(live, project_id) is None


async def test_stub_sorts_materials_by_file_type() -> None:
    sections = [
        TemplateSection(
            id=section_id, title=title, file=f"sections/{section_id}.tex", required=True, guide=""
        )
        for section_id, title in (("goal", "Цель"), ("task", "Задание"), ("progress", "Ход работы"))
    ]
    tools = FakeProjectTools(
        materials={
            path: FakeMaterial(content=b"x" if path.endswith((".pdf", ".png")) else "x")
            for path in (
                "materials/metodichka.pdf",
                "materials/lab.py",
                "materials/screen.png",
                "materials/out.csv",
                "materials/notes.tex",
            )
        },
        guide=DEFAULT_GUIDE.model_copy(update={"sections": sections}),
    )

    result = await plan_stub.make_plan(await plan_request(tools))

    assert result.status == "done"
    assert result.plan is not None
    assert [(s.section_id, s.title, s.materials) for s in result.plan.sections] == [
        ("goal", "Цель", []),
        ("task", "Задание", ["materials/metodichka.pdf"]),
        (
            "progress",
            "Ход работы",
            ["materials/lab.py", "materials/out.csv", "materials/screen.png"],
        ),
    ]
    assert result.plan.unassigned == ["materials/notes.tex"]
    # Заглушка материалы не читает и модель не вызывает.
    assert tools.calls == []
    assert result.usage.tokens_in == 0


async def test_stub_answers_cancel() -> None:
    request = await plan_request(FakeProjectTools())
    request.cancel.set()

    assert (await plan_stub.make_plan(request)).status == "cancelled"


async def test_report_run_gets_confirmed_plan(live: Live, templates: Registry) -> None:
    project_id = await new_project(live)
    async with live.sessionmaker() as session:
        await projects_service.write_text_file(session, writer(), project_id, CODE, "print(1)\n")
        await plans_service.save_generated(
            session, project_id, plan_of(("conclusion", [CODE], "По замерам"))
        )
        await plans_service.confirm_plan(session, project_id)
        await session.commit()
    _, report = await new_run(live, "Напиши отчёт по плану", project_id, kind="report")
    seen: list[ReportPlan | None] = []

    async def agent(request: RunRequest) -> RunResult:
        seen.append(request.plan)
        return RunResult(status="done", text="Готово", usage=PLAN_USAGE)

    await execute(live, report, FakeEvents(), templates, agent, timing=NO_WAIT)
    # Обычное сообщение в чате плана не получает, даже когда план подтверждён.
    _, chat = await new_run(live, "Поправь вывод", project_id)
    await execute(live, chat, FakeEvents(), templates, agent, timing=NO_WAIT)

    [plan, nothing] = seen
    assert plan is not None
    assert [(s.section_id, s.title, s.materials, s.note) for s in plan.sections] == [
        ("goal", "Цель работы", [], ""),
        ("conclusion", "Выводы", [CODE], "По замерам"),
    ]
    assert plan.unassigned == []
    assert nothing is None


async def test_report_run_without_confirmed_plan_gets_none(live: Live, templates: Registry) -> None:
    project_id = await new_project(live)
    async with live.sessionmaker() as session:
        await plans_service.save_generated(session, project_id, plan_of(("goal", [], "")))
        await session.commit()
    _, run_id = await new_run(live, "Напиши отчёт по плану", project_id, kind="report")
    seen: list[ReportPlan | None] = []

    async def agent(request: RunRequest) -> RunResult:
        seen.append(request.plan)
        return RunResult(status="done", text="Готово", usage=PLAN_USAGE)

    await execute(live, run_id, FakeEvents(), templates, agent, timing=NO_WAIT)

    assert seen == [None]


async def test_plan_lock_lets_other_requests_start_runs(live: Live) -> None:
    # Подтверждение держит строку проекта, пока создаёт прогон. Сообщение в чат из соседней
    # вкладки в это время не ждёт её: иначе их вставки прогонов ждали бы друг друга.
    project_id = await new_project(live)
    async with live.sessionmaker() as holding:
        await plans_service.ensure_no_run(holding, project_id)
        async with asyncio.timeout(5):
            _, run_id = await new_run(live, project_id=project_id)
        await holding.rollback()

    assert (await stored_run(live, run_id)).status == "queued"
