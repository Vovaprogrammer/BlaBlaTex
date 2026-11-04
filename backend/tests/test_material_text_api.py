"""GET /projects/{pid}/material-text (architecture.md 9.1): что ИИ видит в материале."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.materials.models import MaterialText
from app.modules.projects.models import File
from tests.helpers import SignUp, create_empty_project

# Any — проект как JSON.
Project = dict[str, Any]
TEXT = "<!-- Страница 1 -->\nЦель работы: изучить сортировки"


@pytest.fixture
async def project(user_client: AsyncClient, db_session: AsyncSession) -> Project:
    me = (await user_client.get("/api/v1/auth/me")).json()
    created = await create_empty_project(db_session, uuid.UUID(me["user"]["id"]))
    pid = str(created.id)
    response = await user_client.post(
        f"/api/v1/projects/{pid}/upload",
        files=[("files", ("task.txt", "Задание".encode())), ("files", ("main.py", b"x = 1\n"))],
        data={"dir": "materials"},
    )
    assert response.status_code == 200, response.text
    await user_client.put(f"/api/v1/projects/{pid}/files/report.tex", content="\\section{}")
    return {"id": pid}


async def set_row(
    session: AsyncSession, project: Project, path: str, **values: str | int | None
) -> None:
    """Как задача извлечения: записывает итог в строку материала."""
    file_id = select(File.id).where(File.project_id == uuid.UUID(project["id"]), File.path == path)
    await session.execute(
        update(MaterialText)
        .where(MaterialText.file_id == file_id.scalar_subquery())
        .values(**values)
    )


async def get(
    client: AsyncClient, project: Project, path: str, **params: int | str
) -> tuple[int, dict[str, Any]]:
    response = await client.get(
        f"/api/v1/projects/{project['id']}/material-text", params={"path": path, **params}
    )
    return response.status_code, response.json()


async def test_ready_material_returns_text_and_details(
    user_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    await set_row(
        db_session,
        project,
        "materials/task.txt",
        status="ready",
        text=TEXT,
        method="pdfminer",
        pages=1,
    )

    status, body = await get(user_client, project, "materials/task.txt")

    assert status == 200
    assert body == {
        "path": "materials/task.txt",
        "status": "ready",
        "method": "pdfminer",
        "pages": 1,
        "description": None,
        "error": None,
        "text": TEXT,
        "offset": 0,
        "total": len(TEXT),
    }


async def test_text_is_returned_in_pieces(
    user_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    await set_row(
        db_session, project, "materials/task.txt", status="ready", text=TEXT, method="text"
    )

    _, piece = await get(user_client, project, "materials/task.txt", offset=20, limit=10)
    _, past_end = await get(user_client, project, "materials/task.txt", offset=1000)

    assert (piece["text"], piece["offset"], piece["total"]) == (TEXT[20:30], 20, len(TEXT))
    assert (past_end["text"], past_end["total"]) == ("", len(TEXT))


async def test_pending_material_has_no_text_yet(user_client: AsyncClient, project: Project) -> None:
    status, body = await get(user_client, project, "materials/main.py")

    assert status == 200
    assert (body["status"], body["text"], body["total"], body["error"]) == (
        "pending",
        None,
        0,
        None,
    )


async def test_failed_material_explains_why(
    user_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    await set_row(
        db_session, project, "materials/task.txt", status="failed", error="PDF защищён паролем"
    )

    status, body = await get(user_client, project, "materials/task.txt")

    assert status == 200
    assert (body["status"], body["text"], body["method"], body["error"]) == (
        "failed",
        None,
        None,
        "PDF защищён паролем",
    )


@pytest.mark.parametrize(
    "path",
    ["materials/missing.txt", "materials", "report.tex"],
    ids=["no-file", "folder", "source"],
)
async def test_not_a_material_is_404(user_client: AsyncClient, project: Project, path: str) -> None:
    status, body = await get(user_client, project, path)

    assert status == 404
    assert body["error"]["code"] == "not_found"


async def test_other_users_project_is_404(
    db_client: AsyncClient, sign_up: SignUp, project: Project
) -> None:
    await sign_up("other@example.com")

    status, _ = await get(db_client, project, "materials/task.txt")

    assert status == 404


@pytest.mark.parametrize(
    "params",
    [
        {"path": "../materials/task.txt"},
        {"path": "materials/task.txt", "offset": -1},
        {"path": "materials/task.txt", "limit": 0},
        {"path": "materials/task.txt", "limit": 100_001},
    ],
    ids=["bad-path", "negative-offset", "zero-limit", "limit-too-big"],
)
async def test_bad_parameters_are_422(
    user_client: AsyncClient, project: Project, params: dict[str, Any]
) -> None:
    response = await user_client.get(
        f"/api/v1/projects/{project['id']}/material-text", params=params
    )

    assert response.status_code == 422, response.text
