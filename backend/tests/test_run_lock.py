"""Блокировка проекта на время прогона и отмена прогона через API (architecture.md 8, 9.1).

Прогон здесь «держит» проект так же, как воркер (history.take_run_lock), но без агента:
проверяется, что во время прогона можно и что нельзя, как блокировка истекает и что
делает POST /runs/{rid}/cancel.
"""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.events import EventType
from app.modules.chat import service as chat_service
from app.modules.chat.dependencies import get_run_enqueue
from app.modules.chat.models import AgentRun, ChatMessage
from app.modules.projects import history
from app.modules.projects import service as projects_service
from app.modules.projects.history import Writer
from app.modules.projects.models import File, Project
from tests.build_worker import BuildWorker
from tests.fake_events import FakeEvents
from tests.helpers import TEST_TEMPLATES, CreateProject, SignUp

EVERYONE_ELSE = "petrov@example.com"


@pytest.fixture
def enqueued(app: FastAPI) -> list[uuid.UUID]:
    """Прогоны, отправленные воркеру; самого воркера нет."""
    run_ids: list[uuid.UUID] = []

    async def enqueue(run_id: uuid.UUID) -> None:
        run_ids.append(run_id)

    app.dependency_overrides[get_run_enqueue] = lambda: enqueue
    return run_ids


def url(project: dict[str, Any], tail: str = "") -> str:
    return f"/api/v1/projects/{project['id']}{tail}"


async def send(client: AsyncClient, project: dict[str, Any], text: str = "Сделай отчёт") -> Any:
    response = await client.post(url(project, "/messages"), json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()


async def start(session: AsyncSession, project: dict[str, Any], run: dict[str, Any]) -> None:
    """Как воркер: прогон занимает проект и идёт."""
    run_id = uuid.UUID(run["id"])
    assert await history.take_run_lock(session, uuid.UUID(project["id"]), run_id)
    await session.execute(update(AgentRun).where(AgentRun.id == run_id).values(status="running"))
    await session.commit()


async def expire_lock(session: AsyncSession, project: dict[str, Any]) -> None:
    """Срок блокировки истёк: воркер упал и перестал её продлевать."""
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project["id"]))
        .values(run_lock_until=func.clock_timestamp() - history.RUN_LOCK_TTL)
    )
    await session.commit()


def assert_locked(response: Any, run: dict[str, Any]) -> None:
    assert response.status_code == 423, response.text
    error = response.json()["error"]
    assert (error["code"], error["details"]) == ("project_locked", {"run_id": run["id"]})


async def test_project_changes_during_run_are_locked(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    db_session: AsyncSession,
) -> None:
    saved = await user_client.put(url(project, "/files/notes.tex"), content="до прогона")
    changesets = (await user_client.get(url(project, "/changesets"))).json()["items"]
    sent = await send(user_client, project)
    await start(db_session, project, sent["run"])
    etag = saved.headers["etag"]

    responses = [
        await user_client.put(
            url(project, "/files/notes.tex"), content="во время", headers={"If-Match": etag}
        ),
        await user_client.put(
            url(project, "/files/new.tex"), content="новый", headers={"If-None-Match": "*"}
        ),
        await user_client.delete(url(project, "/files/notes.tex")),
        await user_client.post(url(project, "/folders"), json={"path": "figures"}),
        await user_client.post(url(project, "/move"), json={"from": "notes.tex", "to": "n.tex"}),
        await user_client.post(
            url(project, "/upload"), files=[("files", ("a.txt", b"x"))], data={"dir": "materials"}
        ),
        await user_client.post(f"/api/v1/changesets/{changesets[0]['id']}/revert"),
        await user_client.patch(
            url(project), json={"fields": {**TEST_TEMPLATES["test-lab"], "lab_title": "Другая"}}
        ),
        await user_client.delete(url(project)),
        await user_client.post(url(project, "/messages"), json={"text": "Ещё"}),
    ]

    for response in responses:
        assert_locked(response, sent["run"])
    assert (await user_client.get(url(project, "/files/notes.tex"))).text == "до прогона"
    tree = (await user_client.get(url(project, "/tree"))).json()["items"]
    assert "new.tex" not in [item["path"] for item in tree]
    assert enqueued == [uuid.UUID(sent["run"]["id"])]


async def test_title_reading_and_builds_work_during_run(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    db_session: AsyncSession,
    build_worker: BuildWorker,
) -> None:
    await start(db_session, project, (await send(user_client, project))["run"])

    renamed = await user_client.patch(url(project), json={"title": "ЛР 3"})
    tree = await user_client.get(url(project, "/tree"))
    main = await user_client.get(url(project, "/files/main.tex"))
    build = await user_client.post(url(project, "/builds"))

    assert (renamed.status_code, renamed.json()["title"]) == (200, "ЛР 3")
    assert (tree.status_code, main.status_code, build.status_code) == (200, 200, 202)


async def test_profile_save_rewrites_meta_during_run(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    db_session: AsyncSession,
) -> None:
    before = await user_client.get(url(project, "/files/meta.tex"))
    await start(db_session, project, (await send(user_client, project))["run"])

    response = await user_client.put(
        "/api/v1/profile",
        json={
            "last_name": "Иванов",
            "first_name": "Иван",
            "middle_name": "",
            "group_name": "БВТ2401",
            "faculty": "",
            "department": "",
        },
    )

    assert response.status_code == 200, response.text
    after = await user_client.get(url(project, "/files/meta.tex"))
    assert "Иванов" in after.text
    assert after.headers["etag"] != before.headers["etag"]


async def test_only_ai_of_the_running_run_writes(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    db_session: AsyncSession,
) -> None:
    project_id = uuid.UUID(project["id"])
    old = await send(user_client, project, "Прошлый запрос")
    await db_session.execute(update(AgentRun).values(status="done"))
    await db_session.commit()
    current = await send(user_client, project)
    await start(db_session, project, current["run"])
    events = FakeEvents()
    owner = uuid.UUID((await user_client.get("/api/v1/auth/me")).json()["user"]["id"])

    def ai(run: dict[str, Any]) -> Writer:
        return Writer(events, "ai", owner, uuid.UUID(run["run"]["changeset_id"]))

    await projects_service.write_text_file(
        db_session, ai(current), project_id, "sections/ai.tex", "ИИ\n"
    )
    with pytest.raises(AppError) as other_run:
        await projects_service.write_text_file(
            db_session, ai(old), project_id, "sections/old.tex", "старый прогон\n"
        )
    assert (other_run.value.status, other_run.value.details) == (
        423,
        {"run_id": current["run"]["id"]},
    )
    # Блокировка истекла — прогон её потерял, и его ИИ тоже больше не пишет.
    await expire_lock(db_session, project)
    with pytest.raises(AppError) as lost:
        await projects_service.write_text_file(
            db_session, ai(current), project_id, "sections/late.tex", "поздно\n"
        )
    assert lost.value.status == 423
    assert await projects_service.find_file(db_session, project_id, "sections/ai.tex") is not None
    assert await projects_service.find_file(db_session, project_id, "sections/late.tex") is None


async def test_expired_lock_frees_project_and_next_message_closes_run(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    db_session: AsyncSession,
    events: FakeEvents,
) -> None:
    sent = await send(user_client, project)
    await start(db_session, project, sent["run"])
    await expire_lock(db_session, project)

    saved = await user_client.put(url(project, "/files/after.tex"), content="можно")
    page = (await user_client.get(url(project, "/messages"))).json()
    second = await send(user_client, project, "Ещё раз")

    assert saved.status_code == 201
    # Прогон умершего воркера уже не активный: вкладка не показывает «Думает…».
    assert page["active_run"] is None
    run = await db_session.get(AgentRun, uuid.UUID(sent["run"]["id"]))
    assert run is not None
    await db_session.refresh(run)
    assert (run.status, run.error) == ("failed", chat_service.RUN_INTERRUPTED_MESSAGE)
    reply = await db_session.get(ChatMessage, uuid.UUID(sent["run"]["message_id"]))
    assert reply is not None
    await db_session.refresh(reply)
    assert reply.parts == [{"type": "error", "text": chat_service.RUN_INTERRUPTED_MESSAGE}]
    closing = [e for e in events.published if e.type.value.startswith(("run.", "project."))]
    assert [e.type for e in closing] == [EventType.RUN_FINISHED, EventType.PROJECT_UNLOCKED]
    assert closing[0].data.model_dump()["status"] == "failed"
    assert second["run"]["status"] == "queued"
    project_row = await db_session.get(Project, uuid.UUID(project["id"]))
    assert project_row is not None
    await db_session.refresh(project_row)
    assert project_row.run_lock_id is None


async def test_cancel_queued_run(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    events: FakeEvents,
) -> None:
    sent = await send(user_client, project)

    response = await user_client.post(f"/api/v1/runs/{sent['run']['id']}/cancel")

    assert response.status_code == 200, response.text
    run = response.json()
    assert (run["status"], run["message_id"]) == ("cancelled", sent["run"]["message_id"])
    assert run["finished_at"] is not None
    # Прогон в очереди не начинался: только run.finished, без блокировки.
    assert events.types == [EventType.RUN_FINISHED]
    finished = events.published[0].data.model_dump()
    assert (finished["status"], str(finished["changeset_id"])) == (
        "cancelled",
        sent["run"]["changeset_id"],
    )
    page = (await user_client.get(url(project, "/messages"))).json()
    assert page["active_run"] is None
    assert [item["status"] for item in page["items"]] == [None, "cancelled"]
    # Можно спросить снова.
    await send(user_client, project, "Снова")


async def test_cancel_running_run_marks_request(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    db_session: AsyncSession,
    events: FakeEvents,
) -> None:
    sent = await send(user_client, project)
    await start(db_session, project, sent["run"])
    cancel_url = f"/api/v1/runs/{sent['run']['id']}/cancel"

    first = await user_client.post(cancel_url)
    run = await db_session.get(AgentRun, uuid.UUID(sent["run"]["id"]))
    assert run is not None
    await db_session.refresh(run)
    requested_at = run.cancel_requested_at
    second = await user_client.post(cancel_url)

    # Идущий прогон останавливает воркер: ответ — прогон как есть, итог придёт событием.
    assert [r.json()["status"] for r in (first, second)] == ["running", "running"]
    assert requested_at is not None
    await db_session.refresh(run)
    assert run.cancel_requested_at == requested_at
    assert events.published == []


async def test_cancel_finished_run_returns_it(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    db_session: AsyncSession,
    events: FakeEvents,
) -> None:
    sent = await send(user_client, project)
    await db_session.execute(update(AgentRun).values(status="done"))
    await db_session.commit()

    response = await user_client.post(f"/api/v1/runs/{sent['run']['id']}/cancel")

    assert (response.status_code, response.json()["status"]) == (200, "done")
    assert events.published == []
    cancelled = await db_session.scalar(
        select(func.count()).select_from(AgentRun).where(AgentRun.cancel_requested_at.isnot(None))
    )
    assert cancelled == 0


async def test_cancel_foreign_or_unknown_run_is_not_found(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    sign_up: SignUp,
    create_project: CreateProject,
) -> None:
    sent = await send(user_client, project)
    await sign_up(EVERYONE_ELSE)
    await create_project()

    for run_id in (sent["run"]["id"], str(uuid.uuid4())):
        response = await user_client.post(f"/api/v1/runs/{run_id}/cancel")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


async def test_lock_does_not_touch_other_projects(
    user_client: AsyncClient,
    project: dict[str, Any],
    enqueued: list[uuid.UUID],
    db_session: AsyncSession,
    create_project: CreateProject,
) -> None:
    other = await create_project(title="ЛР 2")
    await start(db_session, project, (await send(user_client, project))["run"])

    response = await user_client.put(url(other, "/files/notes.tex"), content="свободен")

    assert response.status_code == 201
    count = await db_session.scalar(
        select(func.count()).select_from(File).where(File.path == "notes.tex")
    )
    assert count == 1
