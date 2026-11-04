"""Гонки на настоящих отдельных соединениях: блокировка проекта и сборка во время удаления.

Обычные тесты идут в одной транзакции с откатом, а в одном соединении гонку не увидеть.
Здесь у приложения свой пул к тестовой базе и данные коммитятся по-настоящему. После
теста пользователь удаляется, а с ним и всё его (ON DELETE CASCADE).
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.config import Settings
from app.main import create_app
from app.modules.auth.models import User
from app.modules.builds.dependencies import get_enqueue
from app.modules.builds.models import Build
from app.modules.builds.service import run_project_builds
from app.modules.projects.models import Changeset, Project
from tests.fake_compiler import FakeCompiler
from tests.fake_events import FakeEvents
from tests.helpers import CSRF, PASSWORD, TEST_TEMPLATES, backdate_changesets

MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nГонка\n\\end{document}\n"


@pytest.fixture
async def live_app(db_settings: Settings, tmp_path: Path) -> AsyncIterator[FastAPI]:
    """Приложение с настоящим пулом соединений к тестовой базе. События — в FakeEvents,
    а не в Redis разработчика: lifespan открыл бы настоящий журнал."""
    app = create_app(db_settings.model_copy(update={"storage_dir": tmp_path / "storage"}))
    async with app.router.lifespan_context(app):
        app.state.events = FakeEvents()
        yield app


@pytest.fixture
def fake() -> FakeCompiler:
    return FakeCompiler()


@pytest.fixture
async def live_client(live_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Клиент, вошедший как новый пользователь; после теста пользователь удаляется."""
    email = f"race-{uuid4().hex[:8]}@example.com"
    transport = ASGITransport(app=live_app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=CSRF) as client:
        response = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": PASSWORD, "consent": True}
        )
        assert response.status_code == 201, response.text
        try:
            yield client
        finally:
            async with live_app.state.db_sessionmaker() as session:
                await session.execute(delete(User).where(User.email == email))
                await session.commit()


async def new_project(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={"title": "Гонка", "template_slug": "test-lab", "fields": TEST_TEMPLATES["test-lab"]},
    )
    assert response.status_code == 201, response.text
    project_id: str = response.json()["id"]
    return project_id


async def warm_up_pool(client: AsyncClient, pid: str, connections: int) -> None:
    """Открывает соединения заранее. Иначе первый запрос гонки успевает закончиться,
    пока остальные ещё подключаются к Postgres, и гонки нет."""
    await asyncio.gather(*(client.get(f"/api/v1/projects/{pid}/tree") for _ in range(connections)))


async def test_parallel_writes_with_same_version_conflict(live_client: AsyncClient) -> None:
    pid = await new_project(live_client)
    url = f"/api/v1/projects/{pid}/files/main.tex"
    etag = (await live_client.put(url, content=b"v1")).headers["etag"]
    await warm_up_pool(live_client, pid, 5)

    # Пять вкладок сохраняют одну и ту же версию одновременно.
    responses = await asyncio.gather(
        *(
            live_client.put(url, content=f"w{i}".encode(), headers={"If-Match": etag})
            for i in range(5)
        )
    )

    assert sorted(r.status_code for r in responses) == [200, 412, 412, 412, 412]
    saved = await live_client.get(url)
    # Ровно одна запись поверх версии etag (main.tex уже есть в проекте из шаблона).
    version = int(etag.strip('"'))
    assert saved.headers["etag"] == f'"{version + 1}"'
    [winner] = [r for r in responses if r.status_code == 200]
    assert saved.text == f"w{responses.index(winner)}"


async def test_parallel_writes_into_new_folder(live_client: AsyncClient) -> None:
    pid = await new_project(live_client)

    responses = await asyncio.gather(
        *(
            live_client.put(f"/api/v1/projects/{pid}/files/sections/f{i}.tex", content=b"x")
            for i in range(5)
        )
    )
    tree = (await live_client.get(f"/api/v1/projects/{pid}/tree")).json()["items"]

    assert [r.status_code for r in responses] == [201] * 5
    assert [item["path"] for item in tree].count("sections") == 1


async def test_parallel_saves_share_changeset_and_get_distinct_versions(
    live_app: FastAPI, live_client: AsyncClient
) -> None:
    pid = await new_project(live_client)
    await warm_up_pool(live_client, pid, 5)

    # Пять вкладок одного студента сохраняют разные файлы одновременно.
    responses = await asyncio.gather(
        *(
            live_client.put(f"/api/v1/projects/{pid}/files/f{i}.tex", content=f"{i}".encode())
            for i in range(5)
        )
    )

    assert [r.status_code for r in responses] == [201] * 5
    versions = [r.json()["version"] for r in responses]
    # Номера выдаются по очереди под блокировкой проекта: ни один не повторился.
    assert len(set(versions)) == 5
    async with live_app.state.db_sessionmaker() as session:
        authors = list(
            await session.scalars(select(Changeset.author).where(Changeset.project_id == UUID(pid)))
        )
        last = await session.scalar(
            select(Project.last_file_version).where(Project.id == UUID(pid))
        )
    assert sorted(authors) == ["template", "user"]
    assert last == max(versions)


async def test_revert_and_save_at_the_same_time(
    live_app: FastAPI, live_client: AsyncClient
) -> None:
    pid = await new_project(live_client)
    url = f"/api/v1/projects/{pid}/files/main.tex"
    sessions = live_app.state.db_sessionmaker

    async def next_group() -> None:
        async with sessions() as session:
            await backdate_changesets(session, UUID(pid))
            await session.commit()

    await live_client.put(url, content=b"before")
    await next_group()
    await live_client.put(url, content=b"changeset")
    target = (await live_client.get(f"/api/v1/projects/{pid}/changesets")).json()["items"][0]
    await next_group()
    await warm_up_pool(live_client, pid, 3)

    # Студент откатывает правки, а другая вкладка в этот же момент сохраняет файл.
    reverted, saved = await asyncio.gather(
        live_client.post(f"/api/v1/changesets/{target['id']}/revert"),
        live_client.put(url, content=b"tab"),
    )

    # Что бы ни прошло первым, сохранение вкладки не теряется: откат раньше — вкладка
    # пишет поверх него, вкладка раньше — откат видит изменённый файл и отказывает.
    assert saved.status_code == 200
    assert reverted.status_code in (201, 409), reverted.text
    assert (await live_client.get(url)).text == "tab"


async def test_project_deleted_during_build(
    live_app: FastAPI, live_client: AsyncClient, fake: FakeCompiler
) -> None:
    pid = await new_project(live_client)
    await live_client.put(f"/api/v1/projects/{pid}/files/main.tex", content=MAIN_TEX.encode())
    queued: list[UUID] = []

    async def enqueue(build_id: UUID) -> None:
        queued.append(build_id)

    live_app.dependency_overrides[get_enqueue] = lambda: enqueue
    compiling, release = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        compiling.set()
        await release.wait()
        return fake.build_response()

    fake.respond = respond
    started = await live_client.post(f"/api/v1/projects/{pid}/builds")
    state = live_app.state
    worker = asyncio.create_task(
        run_project_builds(
            state.db_sessionmaker, state.storage, fake.client(), FakeEvents(), queued[0]
        )
    )
    # Пока компилятор собирает, соединение воркера свободно, и удаление не ждёт сборку.
    # Тайм-аут — чтобы тест упал, а не завис, если до компилятора сборка не дойдёт.
    await asyncio.wait_for(compiling.wait(), timeout=5)
    deleted = await asyncio.wait_for(live_client.delete(f"/api/v1/projects/{pid}"), timeout=5)
    release.set()
    await asyncio.wait_for(worker, timeout=5)

    assert started.status_code == 202
    assert deleted.status_code == 204
    # Сборка удалена вместе с проектом; итог воркера записывать некуда.
    async with state.db_sessionmaker() as session:
        assert await session.get(Build, queued[0]) is None


async def test_profile_and_projects_change_together(live_client: AsyncClient) -> None:
    # Правка профиля, новый проект и правка полей одновременно: в итоге meta.tex каждого
    # проекта собран из последнего профиля, а не из того, что видел параллельный запрос.
    pid = await new_project(live_client)
    profile = dict.fromkeys(("last_name", "first_name", "middle_name", "faculty", "department"), "")
    fields = TEST_TEMPLATES["test-lab"] | {"lab_number": 2}

    responses = await asyncio.gather(
        live_client.put("/api/v1/profile", json=profile | {"group_name": "БВТ2401"}),
        new_project(live_client),
        live_client.patch(f"/api/v1/projects/{pid}", json={"fields": fields}),
    )

    assert responses[0].status_code == 200
    assert responses[2].status_code == 200
    for project in (pid, responses[1]):
        meta = await live_client.get(f"/api/v1/projects/{project}/files/meta.tex")
        assert "\\def\\bbtGroup{БВТ2401}" in meta.text
