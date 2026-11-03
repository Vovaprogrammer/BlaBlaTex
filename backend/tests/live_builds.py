"""Сборки на настоящих отдельных соединениях с базой: воркеры, гонки, задачи Taskiq.

Фикстура live — в conftest.py. Данные коммитятся по-настоящему; после теста пользователь
удаляется, а с ним и всё его (ON DELETE CASCADE).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.storage import LocalStorage
from app.modules.builds.models import Build
from app.modules.builds.service import queue_build
from app.modules.projects import service as projects_service
from tests.helpers import create_empty_project

MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nГонка\n\\end{document}\n"


@dataclass
class Live:
    """Пул соединений к тестовой базе, хранилище и владелец проектов теста."""

    sessionmaker: async_sessionmaker[AsyncSession]
    storage: LocalStorage
    owner_id: uuid.UUID


async def new_project(live: Live, text: str = MAIN_TEX) -> uuid.UUID:
    async with live.sessionmaker() as session:
        project = await create_empty_project(session, live.owner_id)
        await projects_service.write_text_file(session, project.id, "main.tex", text)
        return project.id


async def queue(live: Live, project_id: uuid.UUID) -> Build:
    async with live.sessionmaker() as session:
        project = await projects_service.get_project(session, project_id)
        assert project is not None
        build, _ = await queue_build(session, project)
        return build


async def builds_of(live: Live, project_id: uuid.UUID) -> list[Build]:
    async with live.sessionmaker() as session:
        result = await session.scalars(
            select(Build).where(Build.project_id == project_id).order_by(Build.created_at)
        )
        return list(result)
