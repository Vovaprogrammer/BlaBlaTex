"""Таблица builds в базе: допустимые значения, ошибки в JSON и удаление вместе с проектом."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service as auth_service
from app.modules.builds.models import Build
from app.modules.projects import service as projects_service
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate


async def new_project(session: AsyncSession) -> uuid.UUID:
    user, _ = await auth_service.register(session, "ivanov@example.com", "password1")
    data = ProjectCreate(title="ЛР 1", template_slug="test-lab", fields={})
    project = await projects_service.create_project(session, user.id, data)
    return project.id


async def test_errors_default_to_empty_list_and_keep_json(db_session: AsyncSession) -> None:
    project_id = await new_project(db_session)
    error: dict[str, str | int | None] = {
        "file": "sections/intro.tex",
        "line": 12,
        "message": "Undefined control sequence",
        "context": "12 | \\foo",
        "severity": "error",
    }
    db_session.add_all(
        [
            Build(project_id=project_id, status="ok", engine="xelatex"),
            Build(project_id=project_id, status="error", engine="pdflatex", errors=[error]),
        ]
    )
    await db_session.commit()
    db_session.expunge_all()

    builds = await db_session.scalars(
        select(Build).where(Build.project_id == project_id).order_by(Build.status.desc())
    )

    assert [build.errors for build in builds] == [[], [error]]


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("status", "done", "ck_builds_status"),
        # LuaLaTeX компилятор не собирает (architecture.md 6).
        ("engine", "lualatex", "ck_builds_engine"),
    ],
)
async def test_status_and_engine_are_checked(
    db_session: AsyncSession, field: str, value: str, constraint: str
) -> None:
    project_id = await new_project(db_session)
    build = Build(project_id=project_id, status="ok", engine="xelatex")
    setattr(build, field, value)
    db_session.add(build)

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_builds_are_deleted_with_project(db_session: AsyncSession) -> None:
    project_id = await new_project(db_session)
    db_session.add(Build(project_id=project_id, status="ok", engine="xelatex"))
    await db_session.commit()

    project = await db_session.get_one(Project, project_id)
    await projects_service.delete_project(db_session, project)

    assert await db_session.scalar(select(Build).where(Build.project_id == project_id)) is None
