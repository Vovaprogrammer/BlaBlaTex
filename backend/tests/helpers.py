"""Общие константы, типы и хелперы тестов. Фикстуры — в conftest.py."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project

CSRF = {"X-CSRF-Protection": "1"}
STUDENT_EMAIL = "student@example.com"
PASSWORD = "password1"

# Тестовые шаблоны: slug и значения полей. Настоящие шаблоны появятся в A1.2 —
# тогда здесь будут их slug и поля из template.yaml.
TEST_TEMPLATES: dict[str, dict[str, str | int]] = {
    "test-lab": {"lab_number": 1, "lab_title": "Сортировки"},
    "test-vkr": {"topic": "Веб-сервис для отчётов", "supervisor": "Петров П. П."},
}

SignUp = Callable[[str], Awaitable[None]]
SignIn = Callable[[str], Awaitable[None]]
# Any — проект как JSON из ответа API.
CreateProject = Callable[..., Awaitable[dict[str, Any]]]


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
