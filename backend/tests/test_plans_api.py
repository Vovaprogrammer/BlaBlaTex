"""План отчёта (architecture.md 9.1 «План отчёта»): чтение, правка студентом, подтверждение,
запуск составления плана."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.events import EventType, PlanUpdatedData
from app.modules.chat.dependencies import get_run_enqueue
from app.modules.chat.models import AgentRun
from app.modules.chat.router import MESSAGES_LIMIT
from app.modules.plans import service
from app.modules.plans.models import ReportPlanRow
from app.modules.plans.router import PLAN_REQUEST_TEXT
from app.modules.plans.schemas import NOTE_MAX_LENGTH
from app.modules.projects.models import Project
from app.modules.templates import service as templates_service
from tests.fake_events import FakeEvents
from tests.fake_rate_limiter import FakeRateLimiter, RateCheck
from tests.helpers import CreateProject, SignUp

# Any — проект и план как JSON.
Json = dict[str, Any]

TASK = "materials/task.txt"
CODE = "materials/main.py"
NOTE = "Цель — из пункта 1 методички"


def plan_url(project: Json) -> str:
    return f"/api/v1/projects/{project['id']}/plan"


async def upload(client: AsyncClient, project: Json, *names: str) -> None:
    response = await client.post(
        f"/api/v1/projects/{project['id']}/upload",
        files=[("files", (name, b"x = 1\n")) for name in names],
        data={"dir": "materials"},
    )
    assert response.status_code == 200, response.text


@pytest.fixture
async def with_materials(user_client: AsyncClient, project: Json, events: FakeEvents) -> Json:
    """Проект test-lab (разделы goal и conclusion) с двумя материалами. События загрузки
    тестам не нужны."""
    await upload(user_client, project, "task.txt", "main.py")
    events.published.clear()
    return project


async def put_plan(client: AsyncClient, project: Json, sections: list[Json]) -> Any:
    return await client.put(plan_url(project), json={"sections": sections})


async def test_no_plan_yet_is_not_found(user_client: AsyncClient, project: Json) -> None:
    response = await user_client.get(plan_url(project))

    assert response.status_code == 404
    assert response.json()["error"]["message"] == service.PLAN_NOT_FOUND_MESSAGE


async def test_put_creates_plan_by_template_and_materials(
    user_client: AsyncClient, with_materials: Json, events: FakeEvents
) -> None:
    response = await put_plan(
        user_client,
        with_materials,
        # Разделы — не по порядку шаблона, goal без материалов, второй — без заметки.
        [
            {"section_id": "conclusion", "materials": [CODE]},
            {"section_id": "goal", "materials": [TASK, CODE], "note": NOTE},
        ],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["plan"] == {
        "sections": [
            {
                "section_id": "goal",
                "title": "Цель работы",
                "materials": [TASK, CODE],
                "note": NOTE,
            },
            {"section_id": "conclusion", "title": "Выводы", "materials": [CODE], "note": ""},
        ],
        "unassigned": [],
    }
    assert (await user_client.get(plan_url(with_materials))).json() == body
    assert events.types == [EventType.PLAN_UPDATED]
    data = events.published[0].data
    assert isinstance(data, PlanUpdatedData)
    assert data.status == "draft"
    assert data.updated_at.isoformat().replace("+00:00", "Z") == body["updated_at"]


async def test_reading_follows_materials_and_template(
    user_client: AsyncClient, with_materials: Json
) -> None:
    await put_plan(user_client, with_materials, [{"section_id": "goal", "materials": [TASK]}])
    await user_client.delete(f"/api/v1/projects/{with_materials['id']}/files/{TASK}")
    await upload(user_client, with_materials, "plot.py")

    plan = (await user_client.get(plan_url(with_materials))).json()["plan"]

    # Удалённый материал выпал из раздела, а новый и неразложенный — вне плана.
    assert [section["materials"] for section in plan["sections"]] == [[], []]
    assert plan["unassigned"] == [CODE, "materials/plot.py"]


async def test_moved_material_falls_out_of_section(
    user_client: AsyncClient, with_materials: Json
) -> None:
    await put_plan(user_client, with_materials, [{"section_id": "goal", "materials": [CODE]}])
    moved = await user_client.post(
        f"/api/v1/projects/{with_materials['id']}/move",
        json={"from": CODE, "to": "materials/lab.py"},
    )
    assert moved.status_code == 200, moved.text

    plan = (await user_client.get(plan_url(with_materials))).json()["plan"]

    assert plan["sections"][0]["materials"] == []
    assert plan["unassigned"] == ["materials/lab.py", TASK]


@pytest.mark.parametrize(
    ("sections", "loc", "message"),
    [
        ([{"section_id": "intro"}], [0, "section_id"], service.UNKNOWN_SECTION_MESSAGE),
        (
            [{"section_id": "goal"}, {"section_id": "goal"}],
            [1, "section_id"],
            service.REPEATED_SECTION_MESSAGE,
        ),
        (
            [{"section_id": "goal", "materials": [TASK, "materials/nope.py"]}],
            [0, "materials", 1],
            service.UNKNOWN_MATERIAL_MESSAGE,
        ),
        # Файл проекта, но не материал.
        (
            [{"section_id": "goal", "materials": ["main.tex"]}],
            [0, "materials", 0],
            service.UNKNOWN_MATERIAL_MESSAGE,
        ),
        (
            [{"section_id": "goal", "materials": [TASK, TASK]}],
            [0, "materials", 1],
            service.REPEATED_MATERIAL_MESSAGE,
        ),
    ],
)
async def test_put_rejects_unknown_sections_and_materials(
    user_client: AsyncClient,
    with_materials: Json,
    events: FakeEvents,
    sections: list[Json],
    loc: list[str | int],
    message: str,
) -> None:
    response = await put_plan(user_client, with_materials, sections)

    assert response.status_code == 422, response.text
    errors = response.json()["error"]["details"]["errors"]
    assert errors == [
        {"loc": ["body", "sections", *loc], "type": "value_error", "message": message}
    ]
    assert (await user_client.get(plan_url(with_materials))).status_code == 404
    assert events.types == []


async def test_put_rejects_long_note(user_client: AsyncClient, with_materials: Json) -> None:
    note = "я" * (NOTE_MAX_LENGTH + 1)
    response = await put_plan(user_client, with_materials, [{"section_id": "goal", "note": note}])

    assert response.status_code == 422
    loc = response.json()["error"]["details"]["errors"][0]["loc"]
    assert loc == ["body", "sections", 0, "note"]


async def test_put_during_run_is_locked(
    app: FastAPI, user_client: AsyncClient, with_materials: Json, db_session: AsyncSession
) -> None:
    app.dependency_overrides[get_run_enqueue] = lambda: _ignore
    sent = await user_client.post(
        f"/api/v1/projects/{with_materials['id']}/messages", json={"text": "Сделай отчёт"}
    )
    run_id = sent.json()["run"]["id"]

    response = await put_plan(user_client, with_materials, [{"section_id": "goal"}])

    assert response.status_code == 423
    assert response.json()["error"]["details"] == {"run_id": run_id}
    assert await db_session.get(ReportPlanRow, uuid.UUID(with_materials["id"])) is None


async def test_edit_returns_confirmed_plan_to_draft(
    user_client: AsyncClient, with_materials: Json, db_session: AsyncSession
) -> None:
    await put_plan(user_client, with_materials, [{"section_id": "goal", "materials": [TASK]}])
    row = await service.confirm_plan(db_session, uuid.UUID(with_materials["id"]))
    await db_session.commit()
    assert row.status == "confirmed"
    assert (await user_client.get(plan_url(with_materials))).json()["status"] == "confirmed"

    response = await put_plan(user_client, with_materials, [{"section_id": "goal"}])

    assert response.json()["status"] == "draft"


async def test_confirm_needs_plan_and_free_project(
    user_client: AsyncClient, with_materials: Json, db_session: AsyncSession
) -> None:
    project_id = uuid.UUID(with_materials["id"])
    with pytest.raises(AppError) as missing:
        await service.confirm_plan(db_session, project_id)
    assert missing.value.status == 404
    await db_session.rollback()

    await put_plan(user_client, with_materials, [{"section_id": "goal"}])
    run = AgentRun(project_id=project_id, user_id=await _owner(db_session, project_id))
    run.status = "queued"
    db_session.add(run)
    await db_session.commit()

    with pytest.raises(AppError) as locked:
        await service.confirm_plan(db_session, project_id)
    assert locked.value.status == 423
    assert locked.value.details == {"run_id": str(run.id)}


async def test_template_gone_is_not_found(
    user_client: AsyncClient, with_materials: Json, db_session: AsyncSession
) -> None:
    await put_plan(user_client, with_materials, [{"section_id": "goal"}])
    await db_session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(with_materials["id"]))
        .values(template_slug="gone")
    )
    await db_session.commit()

    for response in (
        await user_client.get(plan_url(with_materials)),
        await put_plan(user_client, with_materials, [{"section_id": "goal"}]),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["message"] == templates_service.TEMPLATE_GONE_MESSAGE


async def test_foreign_project_is_not_found(
    user_client: AsyncClient, create_project: CreateProject, sign_up: SignUp
) -> None:
    foreign = await create_project()
    await put_plan(user_client, foreign, [{"section_id": "goal"}])
    await sign_up("other@example.com")

    assert (await user_client.get(plan_url(foreign))).status_code == 404
    response = await put_plan(user_client, foreign, [{"section_id": "goal"}])
    assert response.status_code == 404


async def _ignore(run_id: uuid.UUID) -> None:
    """Очередь, которая ничего не делает: прогон остаётся в очереди."""


async def _owner(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    owner = await session.scalar(select(Project.owner_id).where(Project.id == project_id))
    assert owner is not None
    return owner


async def test_post_plan_queues_plan_run(
    app: FastAPI,
    user_client: AsyncClient,
    with_materials: Json,
    rate_limits: FakeRateLimiter,
) -> None:
    queued: list[uuid.UUID] = []

    async def enqueue(run_id: uuid.UUID) -> None:
        queued.append(run_id)

    app.dependency_overrides[get_run_enqueue] = lambda: enqueue

    response = await user_client.post(plan_url(with_materials))

    assert response.status_code == 201, response.text
    message, run = response.json()["message"], response.json()["run"]
    assert message["parts"] == [{"type": "text", "text": PLAN_REQUEST_TEXT}]
    assert (run["kind"], run["status"]) == ("plan", "queued")
    assert queued == [uuid.UUID(run["id"])]
    me = (await user_client.get("/api/v1/auth/me")).json()["user"]["id"]
    assert rate_limits.checks[-1] == RateCheck("messages", me, MESSAGES_LIMIT)
    chat = await user_client.get(f"/api/v1/projects/{with_materials['id']}/messages")
    assert chat.json()["active_run"]["kind"] == "plan"
    # Второй план, пока первый в очереди, — 423.
    again = await user_client.post(plan_url(with_materials))
    assert again.status_code == 423
    assert again.json()["error"]["details"] == {"run_id": run["id"]}


async def test_post_plan_without_template_is_not_found(
    app: FastAPI, user_client: AsyncClient, with_materials: Json, db_session: AsyncSession
) -> None:
    app.dependency_overrides[get_run_enqueue] = lambda: _ignore
    await db_session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(with_materials["id"]))
        .values(template_slug="gone")
    )
    await db_session.commit()

    response = await user_client.post(plan_url(with_materials))

    assert response.status_code == 404
    runs = await db_session.scalars(
        select(AgentRun).where(AgentRun.project_id == uuid.UUID(with_materials["id"]))
    )
    assert list(runs) == []
