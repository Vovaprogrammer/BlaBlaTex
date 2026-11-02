"""Общие константы, типы и хелперы тестов. Фикстуры — в conftest.py."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects import service as projects_service
from app.modules.projects.models import Project

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


async def create_empty_project(
    session: AsyncSession, owner_id: uuid.UUID, title: str = "ЛР 1"
) -> Project:
    """Проект test-lab без файлов шаблона: тестам сервисов файлов и сборок нужен пустой."""
    new = projects_service.NewProject(
        title=title,
        template_slug="test-lab",
        template_version=1,
        kind="lab",
        engine="xelatex",
        main_file="main.tex",
        fields=TEST_TEMPLATES["test-lab"],
    )
    return await projects_service.create_project(session, owner_id, new, files={})


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
