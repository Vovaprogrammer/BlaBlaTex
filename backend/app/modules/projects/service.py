"""Проекты. Другие модули работают с таблицей projects только через эти функции."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate

# Шаблонов пока нет: эти значения модуль шаблонов (A1.2) возьмёт из template.yaml.
DEFAULT_KIND = "lab"
DEFAULT_TEMPLATE_VERSION = 1
DEFAULT_MAIN_FILE = "main.tex"
DEFAULT_ENGINE = "xelatex"


async def create_project(
    session: AsyncSession, owner_id: uuid.UUID, data: ProjectCreate
) -> Project:
    """Создаёт пустой проект без файлов. Поля шаблона сохраняются как пришли, без проверки."""
    project = Project(
        owner_id=owner_id,
        title=data.title,
        kind=DEFAULT_KIND,
        template_slug=data.template_slug,
        template_version=DEFAULT_TEMPLATE_VERSION,
        fields=data.fields,
        main_file=DEFAULT_MAIN_FILE,
        engine=DEFAULT_ENGINE,
    )
    session.add(project)
    await session.commit()
    return project


async def list_projects(session: AsyncSession, owner_id: uuid.UUID) -> list[Project]:
    """Проекты владельца, недавно изменённые — первыми."""
    result = await session.scalars(
        select(Project)
        .where(Project.owner_id == owner_id)
        .order_by(Project.updated_at.desc(), Project.created_at.desc())
    )
    return list(result)


async def get_owned_project(
    session: AsyncSession, project_id: uuid.UUID, owner_id: uuid.UUID
) -> Project | None:
    """Проект владельца или None: чужой и несуществующий проект не различаются."""
    return await session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    )


async def update_project(session: AsyncSession, project: Project, data: ProjectUpdate) -> Project:
    """Меняет только переданные поля; null — то же, что поле не передано.

    fields заменяются целиком. meta.tex пока не пересоздаётся — это сделает A1.2.
    """
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(project, field, value)
    await session.commit()
    return project


async def delete_project(session: AsyncSession, project: Project) -> None:
    """Удаляет проект; его файлы база удаляет сама (ON DELETE CASCADE)."""
    await session.delete(project)
    await session.commit()
