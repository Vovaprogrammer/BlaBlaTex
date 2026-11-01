"""Таблица files в базе (уникальный путь, согласованность kind) и сервис файлов без HTTP."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.auth import service as auth_service
from app.modules.projects import service as projects_service
from app.modules.projects.models import File, Project
from app.modules.projects.schemas import ProjectCreate


async def new_project(session: AsyncSession, email: str) -> uuid.UUID:
    user, _ = await auth_service.register(session, email, "password1")
    data = ProjectCreate(title="ЛР 1", template_slug="test-lab", fields={})
    project = await projects_service.create_project(session, user.id, data)
    return project.id


def text_file(project_id: uuid.UUID, path: str) -> File:
    return File(project_id=project_id, path=path, kind="text", role="source", content="")


async def test_path_is_unique_within_project(db_session: AsyncSession) -> None:
    first = await new_project(db_session, "ivanov@example.com")
    second = await new_project(db_session, "petrov@example.com")
    db_session.add_all([text_file(first, "main.tex"), text_file(second, "main.tex")])
    await db_session.commit()

    db_session.add(text_file(first, "main.tex"))
    with pytest.raises(IntegrityError, match="uq_files_project_id_path"):
        await db_session.flush()


@pytest.mark.parametrize(
    ("kind", "content", "blob_sha256", "constraint"),
    [
        ("text", None, None, "ck_files_text_content"),
        ("folder", "", None, "ck_files_text_content"),
        ("binary", None, None, "ck_files_binary_blob"),
        ("folder", None, "0" * 64, "ck_files_binary_blob"),
    ],
)
async def test_storage_matches_kind(
    db_session: AsyncSession,
    kind: str,
    content: str | None,
    blob_sha256: str | None,
    constraint: str,
) -> None:
    project_id = await new_project(db_session, "ivanov@example.com")
    db_session.add(
        File(
            project_id=project_id,
            path="x",
            kind=kind,
            role="source",
            content=content,
            blob_sha256=blob_sha256,
        )
    )

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


# Сервис файлов без HTTP: так его будут вызывать ProjectTools (B2.5) и шаблоны (A1.2).


async def test_service_rejects_nul_in_text(db_session: AsyncSession) -> None:
    project_id = await new_project(db_session, "ivanov@example.com")

    with pytest.raises(AppError) as error:
        await projects_service.write_text_file(db_session, project_id, "main.tex", "a\0b")

    assert (error.value.status, error.value.code) == (422, "validation_error")


async def test_writing_into_deleted_project_is_not_found(db_session: AsyncSession) -> None:
    project_id = await new_project(db_session, "ivanov@example.com")
    project = await db_session.get_one(Project, project_id)
    await projects_service.delete_project(db_session, project)

    with pytest.raises(AppError) as error:
        await projects_service.write_text_file(db_session, project_id, "main.tex", "Текст")

    assert (error.value.status, error.value.message) == (404, "Проект не найден")
