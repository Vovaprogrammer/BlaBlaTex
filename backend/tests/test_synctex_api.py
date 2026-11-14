"""SyncTeX сборки (9.1): место в PDF ↔ строка файла через компилятор.

Сборки собирает воркер из tests/build_worker.py с подменным компилятором, запросы SyncTeX
API отправляет своему подменному компилятору (tests/fake_compiler.py).
"""

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import INTERNAL_MESSAGE
from app.core.storage import LocalStorage
from app.modules.builds.dependencies import get_api_compiler
from app.modules.builds.models import Build
from app.modules.builds.router import SYNCTEX_LIMIT
from app.modules.builds.service import (
    SYNCTEX_MISSING_MESSAGE,
    SYNCTEX_TOO_LARGE_MESSAGE,
    SYNCTEX_UNAVAILABLE_MESSAGE,
)
from tests.build_worker import BuildWorker
from tests.fake_compiler import SYNCTEX, FakeCompiler, SyncTexRequest
from tests.fake_rate_limiter import FakeRateLimiter, RateCheck
from tests.helpers import CSRF, SignUp
from tests.test_bearer_auth import issue_token, use_token

# Any в этом файле — сборки и ответы как JSON из API.
MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nПривет\n\\end{document}\n"
SOURCE = {"path": "sections/goal.tex", "line": 3}
BOX = {"page": 2, "x": 85.04, "y": 121.08, "width": 481.89, "height": 12.49}


@pytest.fixture
def api_compiler(app: FastAPI) -> FakeCompiler:
    """Подменный компилятор, к которому API ходит за SyncTeX."""
    fake = FakeCompiler(synctex_answers={"edit": {"source": SOURCE}, "view": {"boxes": [BOX]}})
    client = fake.client()
    app.dependency_overrides[get_api_compiler] = lambda: client
    return fake


@pytest.fixture
async def build(
    user_client: AsyncClient, project: dict[str, Any], build_worker: BuildWorker
) -> dict[str, Any]:
    """Успешная сборка проекта студента с файлом SyncTeX."""
    pid = project["id"]
    response = await user_client.put(f"/api/v1/projects/{pid}/files/main.tex", content=MAIN_TEX)
    assert response.status_code in (200, 201), response.text
    return await build_project(user_client, build_worker, pid)


async def build_project(client: AsyncClient, worker: BuildWorker, pid: str) -> dict[str, Any]:
    queued = await client.post(f"/api/v1/projects/{pid}/builds")
    assert queued.status_code == 202, queued.text
    await worker.run()
    response = await client.get(f"/api/v1/builds/{queued.json()['id']}")
    assert response.json()["status"] == "ok", response.text
    built: dict[str, Any] = response.json()
    return built


def edit_url(build: dict[str, Any], query: str = "page=2&x=300&y=128.5") -> str:
    return f"/api/v1/builds/{build['id']}/synctex/edit?{query}"


def view_url(build: dict[str, Any], query: str = "path=sections/goal.tex&line=3") -> str:
    return f"/api/v1/builds/{build['id']}/synctex/view?{query}"


async def test_edit_answers_source_from_compiler(
    user_client: AsyncClient, build: dict[str, Any], api_compiler: FakeCompiler
) -> None:
    response = await user_client.get(edit_url(build))

    assert response.status_code == 200
    assert response.json() == {"source": SOURCE}
    assert api_compiler.synctex_requests == [
        SyncTexRequest("edit", {"page": "2", "x": "300.0", "y": "128.5"}, SYNCTEX)
    ]


async def test_view_answers_boxes_from_compiler(
    user_client: AsyncClient, build: dict[str, Any], api_compiler: FakeCompiler
) -> None:
    response = await user_client.get(view_url(build, "path=разделы/цель работы.tex&line=7"))

    assert response.status_code == 200
    assert response.json() == {"boxes": [BOX]}
    assert api_compiler.synctex_requests == [
        SyncTexRequest("view", {"path": "разделы/цель работы.tex", "line": "7"}, SYNCTEX)
    ]


async def test_no_student_text_is_not_an_error(
    user_client: AsyncClient, build: dict[str, Any], api_compiler: FakeCompiler
) -> None:
    api_compiler.synctex_answers = {"edit": {"source": None}, "view": {"boxes": []}}

    edit = await user_client.get(edit_url(build, "page=1&x=306&y=780"))
    view = await user_client.get(view_url(build, "path=meta.tex&line=1"))

    assert (edit.status_code, edit.json()) == (200, {"source": None})
    assert (view.status_code, view.json()) == (200, {"boxes": []})


async def test_cached_build_uses_synctex_of_original_build(
    user_client: AsyncClient,
    build: dict[str, Any],
    build_worker: BuildWorker,
    api_compiler: FakeCompiler,
) -> None:
    cached = await build_project(user_client, build_worker, build["project_id"])
    assert len(build_worker.fake.requests) == 1

    response = await user_client.get(edit_url(cached))

    assert response.json() == {"source": SOURCE}
    assert api_compiler.synctex_requests[0].synctex == SYNCTEX


async def test_works_by_token(
    user_client: AsyncClient,
    build: dict[str, Any],
    api_compiler: FakeCompiler,
    rate_limits: FakeRateLimiter,
) -> None:
    me = (await user_client.get("/api/v1/auth/me")).json()["user"]["id"]
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    edit = await user_client.get(edit_url(build))
    view = await user_client.get(view_url(build))

    assert (edit.status_code, view.status_code) == (200, 200)
    # По токену — ещё и лимит самого токена; SyncTeX считается на студента.
    synctex = [check for check in rate_limits.checks if check.name == "synctex"]
    assert synctex == [RateCheck("synctex", me, SYNCTEX_LIMIT)] * 2


async def test_rate_limited_per_student(
    user_client: AsyncClient,
    build: dict[str, Any],
    api_compiler: FakeCompiler,
    rate_limits: FakeRateLimiter,
) -> None:
    me = (await user_client.get("/api/v1/auth/me")).json()["user"]["id"]
    rate_limits.retry_after = 12

    for url in (edit_url(build), view_url(build)):
        response = await user_client.get(url)
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "12"
        assert rate_limits.checks[-1] == RateCheck("synctex", me, SYNCTEX_LIMIT)
    assert (SYNCTEX_LIMIT.count, SYNCTEX_LIMIT.period_s) == (120, 60)
    assert api_compiler.synctex_requests == []


async def test_someone_elses_build_is_not_found(
    user_client: AsyncClient,
    sign_up: SignUp,
    build: dict[str, Any],
    api_compiler: FakeCompiler,
) -> None:
    await sign_up("petrov@example.com")
    user_client.headers.update(CSRF)

    for url in (edit_url(build), view_url(build)):
        response = await user_client.get(url)
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Сборка не найдена"
    unknown = await user_client.get(
        "/api/v1/builds/00000000-0000-0000-0000-000000000000/synctex/edit?page=1&x=1&y=1"
    )
    assert unknown.status_code == 404
    assert api_compiler.synctex_requests == []


async def test_build_without_synctex_is_not_found(
    user_client: AsyncClient,
    project: dict[str, Any],
    build_worker: BuildWorker,
    api_compiler: FakeCompiler,
) -> None:
    # TeX упал раньше, чем записал файл SyncTeX.
    build_worker.fake.files = {"output.log": b"! Emergency stop.\n"}
    build_worker.fake.result = {"status": "error", "exit_code": 1, "duration_ms": 100}
    pid = project["id"]
    await user_client.put(f"/api/v1/projects/{pid}/files/main.tex", content=MAIN_TEX)
    queued = (await user_client.post(f"/api/v1/projects/{pid}/builds")).json()
    await build_worker.run()
    failed = (await user_client.get(f"/api/v1/builds/{queued['id']}")).json()
    assert failed["status"] == "error"

    for url in (edit_url(failed), view_url(failed)):
        response = await user_client.get(url)
        assert response.status_code == 404
        assert response.json()["error"]["message"] == SYNCTEX_MISSING_MESSAGE
    assert api_compiler.synctex_requests == []


async def test_failed_build_with_synctex_answers(
    user_client: AsyncClient,
    project: dict[str, Any],
    build_worker: BuildWorker,
    api_compiler: FakeCompiler,
) -> None:
    # Ошибка LaTeX в nonstopmode: PDF и SyncTeX всё равно есть.
    build_worker.fake.result = {"status": "error", "exit_code": 1, "duration_ms": 100}
    pid = project["id"]
    await user_client.put(f"/api/v1/projects/{pid}/files/main.tex", content=MAIN_TEX)
    queued = (await user_client.post(f"/api/v1/projects/{pid}/builds")).json()
    await build_worker.run()

    response = await user_client.get(edit_url(queued))

    assert response.json() == {"source": SOURCE}


async def test_synctex_file_gone_from_storage(
    user_client: AsyncClient,
    build: dict[str, Any],
    db_session: AsyncSession,
    app: FastAPI,
    api_compiler: FakeCompiler,
) -> None:
    storage: LocalStorage = app.state.storage
    row = await db_session.get(Build, uuid.UUID(build["id"]))
    assert row is not None and row.synctex_sha256 is not None
    await storage.delete(row.synctex_sha256)

    response = await user_client.get(view_url(build))

    assert response.status_code == 404
    assert response.json()["error"]["message"] == SYNCTEX_MISSING_MESSAGE


async def test_build_from_before_synctex_column_filled(
    user_client: AsyncClient,
    build: dict[str, Any],
    db_session: AsyncSession,
    api_compiler: FakeCompiler,
) -> None:
    await db_session.execute(
        update(Build).where(Build.id == uuid.UUID(build["id"])).values(synctex_sha256=None)
    )

    response = await user_client.get(edit_url(build))

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("page=0&x=1&y=1", "page"),
        ("page=a&x=1&y=1", "page"),
        ("x=1&y=1", "page"),
        ("page=1&x=-1&y=1", "x"),
        ("page=1&x=14400.1&y=1", "x"),
        ("page=1&x=nan&y=1", "x"),
        ("page=1&x=1&y=inf", "y"),
        ("page=1&x=1", "y"),
    ],
)
async def test_edit_rejects_bad_query(
    user_client: AsyncClient,
    build: dict[str, Any],
    api_compiler: FakeCompiler,
    query: str,
    field: str,
) -> None:
    response = await user_client.get(edit_url(build, query))

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [error["loc"] for error in errors] == [["query", field]]
    assert api_compiler.synctex_requests == []


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("path=../main.tex&line=1", "path"),
        ("path=/main.tex&line=1", "path"),
        ("path=sections/a:b.tex&line=1", "path"),
        ("path=.hidden.tex&line=1", "path"),
        ("path=a%25b.tex&line=1", "path"),
        ("line=1", "path"),
        ("path=main.tex&line=0", "line"),
        ("path=main.tex&line=10000001", "line"),
        ("path=main.tex", "line"),
    ],
)
async def test_view_rejects_bad_query(
    user_client: AsyncClient,
    build: dict[str, Any],
    api_compiler: FakeCompiler,
    query: str,
    field: str,
) -> None:
    response = await user_client.get(view_url(build, query))

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [error["loc"] for error in errors] == [["query", field]]
    assert api_compiler.synctex_requests == []


async def test_compiler_unavailable(
    user_client: AsyncClient, build: dict[str, Any], api_compiler: FakeCompiler
) -> None:
    api_compiler.error = httpx.ConnectError("compiler is down")

    response = await user_client.get(edit_url(build))

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal",
        "message": SYNCTEX_UNAVAILABLE_MESSAGE,
        "details": {},
    }


async def test_synctex_failure_is_not_unavailability(
    user_client: AsyncClient, build: dict[str, Any], api_compiler: FakeCompiler
) -> None:
    # Компилятор ответил, но synctex упал или не уложился в своё время: «попробуйте через
    # минуту» тут не поможет.
    api_compiler.synctex_status = 500
    api_compiler.synctex_answers["view"] = {"error": {"code": "internal", "message": "x"}}

    response = await user_client.get(view_url(build))

    assert response.status_code == 500
    assert response.json()["error"]["message"] == INTERNAL_MESSAGE


async def test_old_compiler_without_synctex_is_unavailable(
    user_client: AsyncClient, build: dict[str, Any], api_compiler: FakeCompiler
) -> None:
    api_compiler.synctex_status = 404
    api_compiler.synctex_answers["edit"] = {"error": {"code": "not_found", "message": "x"}}

    response = await user_client.get(edit_url(build))

    assert response.status_code == 500
    assert response.json()["error"]["message"] == SYNCTEX_UNAVAILABLE_MESSAGE


async def test_too_large_synctex_file(
    user_client: AsyncClient, build: dict[str, Any], api_compiler: FakeCompiler
) -> None:
    api_compiler.synctex_status = 413
    api_compiler.synctex_answers["view"] = {"error": {"code": "payload_too_large", "message": "x"}}

    response = await user_client.get(view_url(build))

    assert response.status_code == 500
    assert response.json()["error"]["message"] == SYNCTEX_TOO_LARGE_MESSAGE


async def test_database_connection_is_released_before_compiler(
    user_client: AsyncClient,
    build: dict[str, Any],
    api_compiler: FakeCompiler,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Запрос к компилятору бывает долгим, а позицию курсора сайт спрашивает часто.
    in_transaction: list[bool] = []
    answer = api_compiler.synctex_response

    def remember(request: httpx.Request) -> httpx.Response:
        in_transaction.append(db_session.in_transaction())
        return answer(request)

    monkeypatch.setattr(api_compiler, "synctex_response", remember)

    await user_client.get(edit_url(build))
    await user_client.get(view_url(build))

    assert in_transaction == [False, False]


async def test_api_without_compiler_client(user_client: AsyncClient, build: dict[str, Any]) -> None:
    # Без lifespan клиента компилятора нет — это тоже «сервис сборки недоступен».
    response = await user_client.get(view_url(build))

    assert response.status_code == 500
    assert response.json()["error"]["message"] == SYNCTEX_UNAVAILABLE_MESSAGE


@pytest.mark.parametrize(
    ("status", "answer"),
    [
        (422, {"error": {"code": "validation_error", "details": {"errors": [{"loc": ["body"]}]}}}),
        # Ответ не по контракту: страница с нуля и прямоугольник без высоты.
        (200, {"source": {"path": "main.tex", "line": 0}}),
        (200, {"boxes": [{"page": 0, "x": 1, "y": 1, "width": 1}]}),
    ],
)
async def test_compiler_answer_out_of_contract_is_internal_error(
    user_client: AsyncClient,
    build: dict[str, Any],
    api_compiler: FakeCompiler,
    status: int,
    answer: dict[str, Any],
) -> None:
    api_compiler.synctex_status = status
    api_compiler.synctex_answers = {"edit": answer, "view": answer}

    edit = await user_client.get(edit_url(build))
    view = await user_client.get(view_url(build))

    for response in (edit, view):
        assert response.status_code == 500
        assert response.json()["error"]["message"] == INTERNAL_MESSAGE
