"""Таблицы projects и files в базе (движок, уникальный путь, согласованность kind)
и сервис файлов без HTTP."""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import update
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


@pytest.mark.parametrize("engine", ["xelatex", "pdflatex"])
async def test_engine_can_be_xelatex_or_pdflatex(db_session: AsyncSession, engine: str) -> None:
    project_id = await new_project(db_session, "ivanov@example.com")

    await db_session.execute(update(Project).where(Project.id == project_id).values(engine=engine))


async def test_lualatex_engine_is_rejected(db_session: AsyncSession) -> None:
    # Компилятор LuaLaTeX не собирает (architecture.md 6) — в базу такой проект не попадает.
    project_id = await new_project(db_session, "ivanov@example.com")

    with pytest.raises(IntegrityError, match="ck_projects_engine"):
        await db_session.execute(
            update(Project).where(Project.id == project_id).values(engine="lualatex")
        )


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


FAILING_OPERATIONS: dict[str, Callable[[AsyncSession, uuid.UUID], Awaitable[object]]] = {
    "stale version": lambda s, pid: projects_service.write_text_file(
        s, pid, "main.tex", "x", expected_version=7
    ),
    "create only": lambda s, pid: projects_service.write_text_file(
        s, pid, "main.tex", "x", create_only=True
    ),
    "file in place of folder": lambda s, pid: projects_service.write_text_file(
        s, pid, "main.tex/x.tex", "x"
    ),
    "folder on taken path": lambda s, pid: projects_service.create_folder(s, pid, "main.tex"),
    "move missing": lambda s, pid: projects_service.move_path(s, pid, "missing.tex", "x.tex"),
    "move folder into itself": lambda s, pid: projects_service.move_path(
        s, pid, "sections", "sections/old"
    ),
    "delete missing": lambda s, pid: projects_service.delete_path(s, pid, "missing.tex"),
}


@pytest.mark.parametrize("operation", FAILING_OPERATIONS.values(), ids=FAILING_OPERATIONS.keys())
async def test_failed_file_operation_ends_transaction(
    db_session: AsyncSession, operation: Callable[[AsyncSession, uuid.UUID], Awaitable[object]]
) -> None:
    project_id = await new_project(db_session, "ivanov@example.com")
    await projects_service.write_text_file(db_session, project_id, "main.tex", "Текст")
    await projects_service.create_folder(db_session, project_id, "sections")

    with pytest.raises(AppError):
        await operation(db_session, project_id)

    # Агент (этап 2) после ошибки продолжает с той же сессией: транзакция с блокировкой
    # проекта не должна остаться открытой, а сессия — сломанной.
    assert not db_session.in_transaction()
    await projects_service.write_text_file(db_session, project_id, "after.tex", "Дальше")


async def test_writing_into_deleted_project_is_not_found(db_session: AsyncSession) -> None:
    project_id = await new_project(db_session, "ivanov@example.com")
    project = await db_session.get_one(Project, project_id)
    await projects_service.delete_project(db_session, project)

    with pytest.raises(AppError) as error:
        await projects_service.write_text_file(db_session, project_id, "main.tex", "Текст")

    assert (error.value.status, error.value.message) == (404, "Проект не найден")
