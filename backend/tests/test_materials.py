"""Строки material_text (architecture.md 5): когда появляются, сбрасываются и удаляются."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.materials.models import MaterialText
from app.modules.projects import service as projects_service
from app.modules.projects.models import File
from tests.file_samples import PDF, PNG
from tests.helpers import create_empty_project, lab_project

# Any — проект как JSON.
Project = dict[str, Any]
# Что B2.7 и A2.4 запишут в строку: после изменения материала всё это должно стереться.
EXTRACTED = {
    "status": "ready",
    "text": "Цель работы: изучить сортировки",
    "method": "markitdown",
    "pages": 3,
    "description": "Окно программы с результатом 42",
    "error": None,
}


@pytest.fixture
async def project(user_client: AsyncClient, db_session: AsyncSession) -> Project:
    me = (await user_client.get("/api/v1/auth/me")).json()
    created = await create_empty_project(db_session, uuid.UUID(me["user"]["id"]))
    return {"id": str(created.id)}


async def upload(
    client: AsyncClient, project: Project, *files: tuple[str, bytes], folder: str = "materials"
) -> None:
    parts = [("files", (name, data)) for name, data in files]
    response = await client.post(
        f"/api/v1/projects/{project['id']}/upload", files=parts, data={"dir": folder}
    )
    assert response.status_code == 200, response.text


async def put(client: AsyncClient, project: Project, path: str, text: str) -> None:
    response = await client.put(f"/api/v1/projects/{project['id']}/files/{path}", content=text)
    assert response.status_code in (200, 201), response.text


async def move(client: AsyncClient, project: Project, from_: str, to: str) -> Response:
    response = await client.post(
        f"/api/v1/projects/{project['id']}/move", json={"from": from_, "to": to}
    )
    assert response.status_code == 200, response.text
    return response


async def rows(session: AsyncSession, project: Project) -> dict[str, dict[str, Any]]:
    """Путь материала → его строка material_text."""
    result = await session.execute(
        select(File.path, MaterialText)
        .join(MaterialText, MaterialText.file_id == File.id)
        .where(File.project_id == uuid.UUID(project["id"]))
        .execution_options(populate_existing=True)
    )
    return {path: {key: getattr(row, key) for key in EXTRACTED} for path, row in result}


async def extract(session: AsyncSession, project: Project, path: str) -> None:
    """Как B2.7: текст материала извлечён."""
    file_id = select(File.id).where(File.project_id == uuid.UUID(project["id"]), File.path == path)
    await session.execute(
        update(MaterialText)
        .where(MaterialText.file_id == file_id.scalar_subquery())
        .values(**EXTRACTED)
    )


def pending() -> dict[str, Any]:
    return {key: None for key in EXTRACTED} | {"status": "pending"}


async def test_every_uploaded_material_is_pending(
    user_client: AsyncClient, project: Project, db_session: AsyncSession
) -> None:
    await upload(user_client, project, ("shot.png", PNG), ("lab.py", b"x = 1\n"), ("m.pdf", PDF))
    # Вне materials/ — часть отчёта, не материал.
    await upload(user_client, project, ("plot.png", PNG), folder="figures")

    assert await rows(db_session, project) == {
        # Код — тоже материал: B2.7 перенесёт его текст как есть.
        "materials/lab.py": pending(),
        "materials/m.pdf": pending(),
        "materials/shot.png": pending(),
    }


async def test_uploading_material_again_clears_old_text(
    user_client: AsyncClient, project: Project, db_session: AsyncSession
) -> None:
    await upload(user_client, project, ("shot.png", PNG))
    await extract(db_session, project, "materials/shot.png")

    await upload(user_client, project, ("shot.png", PNG + b"new"))

    assert await rows(db_session, project) == {"materials/shot.png": pending()}


async def test_text_written_in_materials_is_pending_and_change_clears_it(
    user_client: AsyncClient, project: Project, db_session: AsyncSession
) -> None:
    await put(user_client, project, "materials/output.txt", "Результат: 41\n")
    created = await rows(db_session, project)
    await extract(db_session, project, "materials/output.txt")

    await put(user_client, project, "materials/output.txt", "Результат: 42\n")

    assert created == {"materials/output.txt": pending()}
    assert await rows(db_session, project) == {"materials/output.txt": pending()}


async def test_rename_inside_materials_keeps_extracted_text(
    user_client: AsyncClient, project: Project, db_session: AsyncSession
) -> None:
    await upload(user_client, project, ("lab.py", b"x = 1\n"))
    await extract(db_session, project, "materials/lab.py")

    await move(user_client, project, "materials/lab.py", "materials/lab3/main.py")

    assert await rows(db_session, project) == {"materials/lab3/main.py": EXTRACTED}


async def test_moving_out_of_materials_and_back(
    user_client: AsyncClient, project: Project, db_session: AsyncSession
) -> None:
    await upload(user_client, project, ("lab.py", b"x = 1\n"))
    await extract(db_session, project, "materials/lab.py")

    await move(user_client, project, "materials/lab.py", "src/lab.py")
    out = await rows(db_session, project)
    await move(user_client, project, "src/lab.py", "materials/lab.py")

    assert out == {}
    # Строку удалили при выносе — текст придётся извлечь заново.
    assert await rows(db_session, project) == {"materials/lab.py": pending()}


async def test_moving_folders_with_materials(
    user_client: AsyncClient, project: Project, db_session: AsyncSession
) -> None:
    await upload(user_client, project, ("lab3/shot.png", PNG), ("lab3/lab.py", b"x = 1\n"))
    await extract(db_session, project, "materials/lab3/shot.png")

    await move(user_client, project, "materials/lab3", "materials/lab4")
    renamed = await rows(db_session, project)
    await move(user_client, project, "materials/lab4", "archive")
    moved_out = await rows(db_session, project)
    await move(user_client, project, "archive", "materials/archive")

    assert renamed == {"materials/lab4/shot.png": EXTRACTED, "materials/lab4/lab.py": pending()}
    assert moved_out == {}
    assert await rows(db_session, project) == {
        "materials/archive/lab.py": pending(),
        "materials/archive/shot.png": pending(),
    }


async def test_rows_go_away_with_file_and_project(
    user_client: AsyncClient, project: Project, db_session: AsyncSession
) -> None:
    await upload(user_client, project, ("shot.png", PNG), ("lab.py", b"x = 1\n"))

    deleted = await user_client.delete(f"/api/v1/projects/{project['id']}/files/materials/lab.py")
    after_file = await rows(db_session, project)
    removed = await user_client.delete(f"/api/v1/projects/{project['id']}")

    assert (deleted.status_code, removed.status_code) == (204, 204)
    assert list(after_file) == ["materials/shot.png"]
    assert await db_session.scalar(select(func.count()).select_from(MaterialText)) == 0


async def test_materials_of_a_new_project_are_pending(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    me = (await user_client.get("/api/v1/auth/me")).json()
    created = await projects_service.create_project(
        db_session,
        uuid.UUID(me["user"]["id"]),
        lab_project("ЛР 2"),
        files={"main.tex": "\\begin{document}\\end{document}\n", "materials/task.md": "Задание"},
    )

    assert await rows(db_session, {"id": str(created.id)}) == {"materials/task.md": pending()}
