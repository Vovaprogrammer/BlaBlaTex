"""POST /projects/{pid}/checks — проверки отчёта для сайта и агента по токену (9.1).

Сборки собирает тестовый воркер (BuildWorker) с подменным компилятором; тот же
компилятор API спрашивает о версии, чтобы найти сборку текущих файлов.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from app.core.config import Settings
from app.modules.builds.dependencies import get_api_compiler, get_enqueue
from app.modules.builds.models import Build
from app.modules.builds.router import BUILDS_LIMIT
from app.modules.projects.models import Project
from tests.build_worker import BuildWorker
from tests.checks_pdf_samples import OVERFLOW, PROGRESS
from tests.checks_samples import FIXTURES
from tests.fake_rate_limiter import FakeRateLimiter, RateCheck
from tests.helpers import CSRF, TEST_TEMPLATES, CreateProject, running_app, signed_up_client
from tests.test_bearer_auth import issue_token, use_token

API = "/api/v1"
# Any — JSON из ответа API: его вид проверяют сами тесты.
Json = dict[str, Any]
GOAL = "sections/goal.tex"
SECRET = "Секретная фраза студента"


def checks_url(project: Json) -> str:
    return f"{API}/projects/{project['id']}/checks"


async def write(client: AsyncClient, project: Json, path: str, text: str) -> None:
    """Перезаписывает файл проекта, как редактор сайта: с версией из ETag."""
    url = f"{API}/projects/{project['id']}/files/{path}"
    current = await client.get(url)
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    headers["If-Match" if current.status_code == 200 else "If-None-Match"] = (
        current.headers["etag"] if current.status_code == 200 else "*"
    )
    response = await client.put(url, content=text.encode(), headers=headers)
    assert response.status_code in (200, 201), response.text


async def check(client: AsyncClient, project: Json, **params: int) -> Json:
    response = await client.post(checks_url(project), params=params)
    assert response.status_code == 200, response.text
    result: Json = response.json()
    return result


def builds_checked(rate_limits: FakeRateLimiter) -> list[RateCheck]:
    """Проверки лимита сборок: регистрация и вход тоже проверяют свои лимиты."""
    return [entry for entry in rate_limits.checks if entry.name == "builds"]


async def owner_of(client: AsyncClient) -> str:
    owner: str = (await client.get(f"{API}/auth/me")).json()["user"]["id"]
    return owner


@pytest.fixture
def worker(app: FastAPI, build_worker: BuildWorker) -> BuildWorker:
    """Воркер сборок; API спрашивает версию у того же подменного компилятора."""
    app.dependency_overrides[get_api_compiler] = build_worker.fake.client
    return build_worker


async def test_checks_queue_build_once_then_use_it(
    user_client: AsyncClient,
    worker: BuildWorker,
    project: Json,
    rate_limits: FakeRateLimiter,
) -> None:
    await write(user_client, project, GOAL, "\\section{Цель работы}\nTODO: цель.\n")

    first = await check(user_client, project)

    assert [(f["check"], f["file"], f["line"]) for f in first["findings"]] == [
        ("placeholder", GOAL, 2)
    ]
    assert first["findings"][0] == {
        "check": "placeholder",
        "level": "error",
        "message": "В тексте осталась заглушка «TODO». Замените её настоящим текстом или "
        "попросите ИИ дописать это место по материалам.",
        "file": GOAL,
        "line": 2,
        "place": "file",
        "field": None,
    }
    assert (first["errors_count"], first["warnings_count"]) == (1, 0)
    # Сборки текущих файлов не было: проверки её поставили и в лимит сборок засчитали.
    assert first["pdf_checked"] is False
    assert worker.queued == [uuid.UUID(first["build_id"])]
    owner = await owner_of(user_client)
    assert builds_checked(rate_limits) == [RateCheck("builds", owner, BUILDS_LIMIT)]

    await worker.run()
    second = await check(user_client, project)

    # Теперь сборка есть: проверки берут её, новой не ставят и лимит не тратят.
    assert second["pdf_checked"] is True
    assert second["build_id"] == first["build_id"]
    assert second["findings"] == first["findings"]
    assert worker.queued == []
    assert len(builds_checked(rate_limits)) == 1


async def test_changed_files_need_new_build(
    user_client: AsyncClient, worker: BuildWorker, project: Json
) -> None:
    first = await check(user_client, project)
    await worker.run()
    await write(user_client, project, GOAL, "\\section{Цель работы}\nИзучить поиск.\n")

    second = await check(user_client, project)

    assert second["build_id"] != first["build_id"]
    assert second["pdf_checked"] is False


async def test_pdf_findings_from_build_log(
    user_client: AsyncClient, worker: BuildWorker, project: Json
) -> None:
    main = (
        "\\documentclass{mtuci-report}\n\\input{meta}\n\\begin{document}\n"
        "\\input{sections/progress}\n\\end{document}\n"
    )
    await write(user_client, project, "main.tex", main)
    await write(user_client, project, PROGRESS, OVERFLOW[PROGRESS])
    worker.fake.files["output.log"] = (FIXTURES / "overflow.log").read_bytes()
    await check(user_client, project)
    await worker.run()

    result = await check(user_client, project)

    overflow = [(f["file"], f["line"]) for f in result["findings"] if f["check"] == "text-overflow"]
    assert overflow == [(PROGRESS, 3), (PROGRESS, 5)]


async def test_failed_build_is_one_finding_without_file(
    user_client: AsyncClient, worker: BuildWorker, project: Json
) -> None:
    worker.fake.result = {"status": "error", "exit_code": 1, "duration_ms": 900}
    worker.fake.files = {"output.log": b"./main.tex:3: Undefined control sequence.\nl.3 \\foo\n"}
    await check(user_client, project)
    await worker.run()

    result = await check(user_client, project)

    [failed] = [f for f in result["findings"] if f["check"] == "build-failed"]
    assert (failed["file"], failed["line"], failed["place"]) == (None, None, "build")
    assert result["findings"][0] == failed


async def test_agent_by_token(user_client: AsyncClient, worker: BuildWorker, project: Json) -> None:
    use_token(user_client, (await issue_token(user_client))["token"])

    result = await check(user_client, project)

    assert result["build_id"] is not None


async def test_foreign_project_is_not_found(
    user_client: AsyncClient, create_project: CreateProject, sign_up: Any
) -> None:
    foreign = await create_project()
    await sign_up("other@example.com")

    response = await user_client.post(checks_url(foreign), headers=CSRF)

    assert response.status_code == 404


@pytest.mark.parametrize("wait", [-1, 61])
async def test_wait_out_of_range(user_client: AsyncClient, project: Json, wait: int) -> None:
    response = await user_client.post(checks_url(project), params={"wait": wait})

    assert response.status_code == 422
    [error] = response.json()["error"]["details"]["errors"]
    assert error["loc"] == ["query", "wait"]


async def test_build_limit_is_shared_with_builds(
    user_client: AsyncClient,
    worker: BuildWorker,
    project: Json,
    rate_limits: FakeRateLimiter,
    db_session: AsyncSession,
) -> None:
    rate_limits.retry_after = 30

    response = await user_client.post(checks_url(project))

    assert response.status_code == 429
    assert response.json()["error"]["details"]["retry_after"] == 30
    builds = await db_session.scalar(select(func.count()).select_from(Build))
    assert builds == 0


async def test_checks_work_while_ai_runs(
    user_client: AsyncClient, worker: BuildWorker, project: Json, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project["id"]))
        .values(run_lock_id=uuid.uuid4(), run_lock_until=func.now() + timedelta(minutes=5))
    )
    await db_session.commit()

    locked = await user_client.put(
        f"{API}/projects/{project['id']}/files/notes.tex",
        content=b"x",
        headers={"If-None-Match": "*", "Content-Type": "text/plain; charset=utf-8"},
    )
    response = await user_client.post(checks_url(project))

    assert locked.status_code == 423
    assert response.status_code == 200


async def test_template_without_checks_needs_no_build(
    user_client: AsyncClient, worker: BuildWorker, create_project: CreateProject
) -> None:
    project = await create_project("test-any-lab")

    result = await check(user_client, project)

    assert result == {
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
        "build_id": None,
        "pdf_checked": True,
    }
    assert worker.queued == []


async def test_log_has_no_student_text(
    user_client: AsyncClient, worker: BuildWorker, project: Json
) -> None:
    await write(user_client, project, GOAL, f"\\section{{Цель работы}}\n{SECRET} TODO.\n")

    with capture_logs() as logs:
        await check(user_client, project)

    [done] = [entry for entry in logs if entry["event"] == "checks_done"]
    assert set(done) >= {"project_id", "build_id", "errors", "warnings", "duration_ms"}
    assert SECRET not in repr(logs)
    assert "TODO" not in repr(logs)


# На настоящем пуле соединений: ожидание сборки не держит соединение.


async def _no_queue(build_id: uuid.UUID) -> None:
    """Сборку никто не собирает: тест сам ставит ей итог."""


@pytest.fixture
async def pool_app(db_settings: Settings, tmp_path: Path) -> AsyncIterator[FastAPI]:
    settings = db_settings.model_copy(
        update={"storage_dir": tmp_path / "storage", "db_pool_size": 1, "db_max_overflow": 0}
    )
    async with running_app(settings) as app:
        app.dependency_overrides[get_enqueue] = lambda: _no_queue
        app.dependency_overrides[get_api_compiler] = lambda: None
        yield app


@pytest.fixture
async def pool_client(pool_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with signed_up_client(pool_app, "checks") as client:
        yield client


async def new_project(client: AsyncClient) -> Json:
    body = {"title": "ЛР 1", "template_slug": "test-lab", "fields": TEST_TEMPLATES["test-lab"]}
    response = await client.post(f"{API}/projects", json=body)
    assert response.status_code == 201, response.text
    project: Json = response.json()
    return project


async def finish_queued(app: FastAPI, after_s: float) -> None:
    """Через after_s секунд сборка в очереди заканчивается — как у воркера."""
    await asyncio.sleep(after_s)
    async with app.state.db_sessionmaker() as session:
        await session.execute(update(Build).where(Build.status == "queued").values(status="ok"))
        await session.commit()


async def test_wait_returns_when_build_finishes(
    pool_app: FastAPI, pool_client: AsyncClient
) -> None:
    project = await new_project(pool_client)
    started = time.monotonic()

    response, _ = await asyncio.gather(
        pool_client.post(checks_url(project), params={"wait": 30}),
        finish_queued(pool_app, after_s=0.3),
    )

    assert response.json()["pdf_checked"] is True
    assert time.monotonic() - started < 5


async def test_waiting_checks_do_not_hold_connection(
    pool_app: FastAPI, pool_client: AsyncClient
) -> None:
    project = await new_project(pool_client)
    waiting = asyncio.create_task(pool_client.post(checks_url(project), params={"wait": 30}))
    await asyncio.sleep(0.5)

    # Соединение в пуле одно: если бы его держало ожидание, этот запрос встал бы.
    tree = await asyncio.wait_for(pool_client.get(f"{API}/projects/{project['id']}/tree"), 5)

    assert tree.status_code == 200
    assert not waiting.done()
    await finish_queued(pool_app, after_s=0)
    assert (await waiting).json()["pdf_checked"] is True


async def test_shutdown_answers_without_pdf_checks(
    pool_app: FastAPI, pool_client: AsyncClient
) -> None:
    project = await new_project(pool_client)
    waiting = asyncio.create_task(pool_client.post(checks_url(project), params={"wait": 30}))
    await asyncio.sleep(0.5)

    pool_app.state.shutdown.set()
    response = await asyncio.wait_for(waiting, 5)

    assert response.status_code == 200
    assert response.json()["pdf_checked"] is False
