"""Общие константы, типы и хелперы тестов. Фикстуры — в conftest.py."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import URL, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.events import Author
from app.modules.projects import service as projects_service
from app.modules.projects.history import Writer
from app.modules.projects.models import Changeset, Project
from tests.fake_events import FakeEvents

CSRF = {"X-CSRF-Protection": "1"}
STUDENT_EMAIL = "student@example.com"
PASSWORD = "password1"

# Шаблоны-фикстуры: тесты не зависят от настоящих шаблонов в templates/.
TEMPLATE_FIXTURES = Path(__file__).parent / "fixtures" / "templates"
# Шаблоны-фикстуры: slug и значения обязательных полей из их template.yaml.
TEST_TEMPLATES: dict[str, dict[str, str | int]] = {
    "test-lab": {"lab_number": 1, "lab_title": "Сортировки"},
    "test-vkr": {"topic": "Веб-сервис для отчётов", "supervisor": "Петров П. П."},
}

SignUp = Callable[[str], Awaitable[None]]
SignIn = Callable[[str], Awaitable[None]]
# Any — проект как JSON из ответа API.
CreateProject = Callable[..., Awaitable[dict[str, Any]]]


def writer(
    events: FakeEvents | None = None,
    user_id: uuid.UUID | None = None,
    author: Author = "user",
) -> Writer:
    """Кто пишет файлы в тестах сервиса: по умолчанию студент без id, события — в FakeEvents."""
    return Writer(events or FakeEvents(), author, user_id)


def lab_project(title: str = "ЛР 1") -> projects_service.NewProject:
    """Новый проект из шаблона-фикстуры test-lab — для create_project в тестах сервисов."""
    return projects_service.NewProject(
        title=title,
        template_slug="test-lab",
        template_version=1,
        kind="lab",
        engine="xelatex",
        main_file="main.tex",
        fields=TEST_TEMPLATES["test-lab"],
    )


async def create_empty_project(
    session: AsyncSession, owner_id: uuid.UUID, title: str = "ЛР 1"
) -> Project:
    """Проект test-lab без файлов шаблона: тестам сервисов файлов и сборок нужен пустой."""
    return await projects_service.create_project(session, owner_id, lab_project(title), files={})


async def backdate_project(session: AsyncSession, project_id: str, hours: int) -> datetime:
    """Сдвигает время изменения проекта на hours часов назад и возвращает его.

    Между двумя запросами теста часы могут не сдвинуться, и сравнение времени было бы
    случайным; с запасом в час порядок известен заранее.
    """
    moment = datetime.now(UTC) - timedelta(hours=hours)
    await session.execute(
        update(Project).where(Project.id == uuid.UUID(project_id)).values(updated_at=moment)
    )
    return moment


async def backdate_changesets(
    session: AsyncSession, project_id: uuid.UUID, minutes: int = 11
) -> None:
    """Сдвигает changesets проекта на minutes минут назад. По умолчанию — дальше склейки
    (10 минут): следующая правка студента начнёт новый changeset."""
    await session.execute(
        update(Changeset)
        .where(Changeset.project_id == project_id)
        .values(created_at=Changeset.created_at - timedelta(minutes=minutes))
    )


async def drop_database(url: URL, name: str, *, create_again: bool) -> None:
    """Удаляет базу name, если она есть; при create_again создаёт её снова пустой."""
    # CREATE и DROP DATABASE не работают внутри транзакции — нужен AUTOCOMMIT.
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    quoted = engine.dialect.identifier_preparer.quote(name)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"))
            if create_again:
                await connection.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        await engine.dispose()
