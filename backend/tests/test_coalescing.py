"""Склейка автосохранений (architecture.md 5): правки студента за 10 минут от первой —
один changeset, пока не вмешается другой автор или откат."""

import uuid
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects import service as projects_service
from app.modules.projects.history import Writer
from app.modules.projects.models import Changeset, FileRevision
from tests.fake_events import FakeEvents
from tests.helpers import CSRF, backdate_changesets

# Any — проект как JSON из ответа API.
Json = dict[str, Any]
PROFILE = dict.fromkeys(("last_name", "first_name", "middle_name", "faculty", "department"), "")


def file_url(project: Json, path: str) -> str:
    return f"/api/v1/projects/{project['id']}/files/{path}"


async def save(client: AsyncClient, project: Json, path: str, text: str) -> None:
    response = await client.put(file_url(project, path), content=text.encode())
    assert response.status_code in (200, 201), response.text


async def authors(session: AsyncSession, project: Json) -> list[str]:
    """Авторы changesets проекта по порядку, без создания из шаблона."""
    result = await session.scalars(
        select(Changeset.author)
        .where(Changeset.project_id == uuid.UUID(project["id"]), Changeset.author != "template")
        .order_by(Changeset.created_at)
    )
    return list(result)


async def test_autosaves_within_ten_minutes_are_one_changeset(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    for text in ("Ч", "Че", "Чер"):
        await save(user_client, project, "notes.tex", text)
    await save(user_client, project, "main.tex", "Новый main")
    await user_client.post(f"/api/v1/projects/{project['id']}/folders", json={"path": "img"})

    assert await authors(db_session, project) == ["user"]
    changeset = await db_session.scalar(
        select(Changeset).where(
            Changeset.project_id == uuid.UUID(project["id"]), Changeset.author == "user"
        )
    )
    assert changeset is not None
    assert changeset.updated_at >= changeset.created_at
    # Вид каждого файла до changeset сохранён один раз — сколько бы раз его ни сохраняли.
    touched = await db_session.scalars(
        select(FileRevision.path).where(FileRevision.changeset_id == changeset.id)
    )
    assert sorted(touched, key=lambda path: path or "") == [None, None, "main.tex"]


async def test_window_counts_from_first_edit(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    pid = uuid.UUID(project["id"])
    await save(user_client, project, "notes.tex", "1")
    await backdate_changesets(db_session, pid, minutes=9)
    # Последняя правка была только что, но changeset начат 9 минут назад — ещё склеивается.
    await save(user_client, project, "notes.tex", "2")
    await backdate_changesets(db_session, pid, minutes=2)

    await save(user_client, project, "notes.tex", "3")

    assert await authors(db_session, project) == ["user", "user"]


async def test_other_tab_of_same_student_joins_changeset(
    app: FastAPI, user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "из первой вкладки")

    # Вторая вкладка — свой клиент с той же сессией студента.
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=user_client.cookies, headers=CSRF
    ) as tab:
        await save(tab, project, "b.tex", "из второй вкладки")

    assert await authors(db_session, project) == ["user"]


async def test_ai_write_breaks_coalescing(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    pid = uuid.UUID(project["id"])
    await save(user_client, project, "notes.tex", "студент")
    run = Changeset(project_id=pid, author="ai")
    db_session.add(run)
    await db_session.flush()
    ai = Writer(FakeEvents(), "ai", None, run.id)

    await projects_service.write_text_file(db_session, ai, pid, "notes.tex", "ИИ")
    await save(user_client, project, "notes.tex", "снова студент")

    assert await authors(db_session, project) == ["user", "ai", "user"]


async def test_meta_rebuild_breaks_coalescing(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "notes.tex", "до профиля")
    response = await user_client.put("/api/v1/profile", json=PROFILE | {"group_name": "БВТ2401"})
    assert response.status_code == 200

    await save(user_client, project, "notes.tex", "после профиля")

    assert await authors(db_session, project) == ["user", "system", "user"]


async def test_unchanged_meta_does_not_break_coalescing(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "notes.tex", "1")
    # Название проекта meta.tex не меняет — записи нет, и склейка продолжается.
    await user_client.patch(f"/api/v1/projects/{project['id']}", json={"title": "ЛР 2"})

    await save(user_client, project, "notes.tex", "2")

    assert await authors(db_session, project) == ["user"]


async def test_mcp_and_site_are_different_authors(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    pid = uuid.UUID(project["id"])
    await save(user_client, project, "notes.tex", "с сайта")
    owner = await db_session.scalar(
        select(Changeset.author_user_id).where(Changeset.project_id == pid)
    )
    mcp = Writer(FakeEvents(), "mcp", owner)

    await projects_service.write_text_file(db_session, mcp, pid, "notes.tex", "из Claude Code")
    await projects_service.write_text_file(db_session, mcp, pid, "notes.tex", "ещё раз")

    assert await authors(db_session, project) == ["user", "mcp"]


async def test_failed_write_does_not_start_changeset(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    refused = await user_client.put(
        file_url(project, "notes.tex"), content=b"x", headers={"If-Match": '"999"', **CSRF}
    )

    assert refused.status_code == 412
    assert await authors(db_session, project) == []
