"""Таблицы chat_messages и agent_runs: допустимые значения, один активный прогон на проект,
порядок сообщений и удаление вместе с проектом."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service as auth_service
from app.modules.chat.models import ONE_ACTIVE_RUN_INDEX, AgentRun, ChatMessage
from app.modules.projects import history
from app.modules.projects.models import Changeset, Project
from tests.helpers import create_empty_project


async def new_project(session: AsyncSession, email: str = "ivanov@example.com") -> Project:
    user, _ = await auth_service.register(session, email, "password1")
    return await create_empty_project(session, user.id)


async def new_run(session: AsyncSession, project: Project, status: str = "queued") -> AgentRun:
    """Прогон с changeset — в том порядке, в каком их создаёт сервис чата."""
    run = AgentRun(project_id=project.id, user_id=project.owner_id, status=status)
    session.add(run)
    await session.flush()
    changeset = await history.create_changeset(
        session, project.id, "ai", project.owner_id, run_id=run.id
    )
    run.changeset_id = changeset.id
    await session.flush()
    return run


async def test_run_defaults_and_changeset_link(db_session: AsyncSession) -> None:
    project = await new_project(db_session)
    run = await new_run(db_session, project)
    await db_session.commit()
    db_session.expunge_all()

    stored = await db_session.get(AgentRun, run.id)
    assert stored is not None
    assert (stored.status, stored.model, stored.tokens_in, stored.tokens_out) == (
        "queued",
        None,
        0,
        0,
    )
    assert stored.cost == Decimal(0)
    assert stored.finished_at is None
    changeset = await db_session.get(Changeset, stored.changeset_id)
    assert changeset is not None
    assert (changeset.author, changeset.run_id) == ("ai", run.id)


@pytest.mark.parametrize(
    ("model", "field", "value", "constraint"),
    [
        (AgentRun, "status", "paused", "ck_agent_runs_status"),
        (ChatMessage, "role", "tool", "ck_chat_messages_role"),
    ],
)
async def test_status_and_role_are_checked(
    db_session: AsyncSession, model: type, field: str, value: str, constraint: str
) -> None:
    project = await new_project(db_session)
    if model is AgentRun:
        row = AgentRun(project_id=project.id, user_id=project.owner_id, status="queued")
    else:
        row = ChatMessage(project_id=project.id, role="user")
    setattr(row, field, value)
    db_session.add(row)

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


@pytest.mark.parametrize("active", ["queued", "running"])
async def test_one_active_run_per_project(db_session: AsyncSession, active: str) -> None:
    project = await new_project(db_session)
    other = await new_project(db_session, "petrov@example.com")
    for status in ("done", "failed", "cancelled"):
        await new_run(db_session, project, status)
    await new_run(db_session, project, active)
    # Активный прогон другого проекта не мешает.
    await new_run(db_session, other, "running")

    with pytest.raises(IntegrityError, match=ONE_ACTIVE_RUN_INDEX):
        await new_run(db_session, project, "queued")


async def test_messages_keep_insert_order_and_parts(db_session: AsyncSession) -> None:
    project = await new_project(db_session)
    parts = [
        {"type": "text", "text": "Проверю файлы"},
        {"type": "tool", "call_id": "c1", "tool": "list_files", "summary": "Список файлов"},
    ]
    # Одна транзакция, одно время создания: порядок держит position.
    db_session.add_all(
        [
            ChatMessage(project_id=project.id, role="user", parts=[{"type": "text", "text": "Да"}]),
            ChatMessage(project_id=project.id, role="assistant"),
            ChatMessage(project_id=project.id, role="assistant", parts=parts, seq=2),
        ]
    )
    await db_session.commit()
    db_session.expunge_all()

    rows = list(
        await db_session.scalars(
            select(ChatMessage)
            .where(ChatMessage.project_id == project.id)
            .order_by(ChatMessage.position)
        )
    )

    assert [(row.role, row.seq) for row in rows] == [
        ("user", 0),
        ("assistant", 0),
        ("assistant", 2),
    ]
    assert rows[1].parts == []
    assert rows[2].parts == parts


async def test_changeset_run_must_exist(db_session: AsyncSession) -> None:
    project = await new_project(db_session)

    with pytest.raises(IntegrityError, match="fk_changesets_run_id_agent_runs"):
        await history.create_changeset(
            db_session, project.id, "ai", project.owner_id, run_id=uuid.uuid4()
        )


async def test_project_delete_removes_chat_and_runs(db_session: AsyncSession) -> None:
    project = await new_project(db_session)
    run = await new_run(db_session, project, "running")
    db_session.add_all(
        [
            ChatMessage(project_id=project.id, run_id=run.id, role="user"),
            ChatMessage(project_id=project.id, run_id=run.id, role="assistant"),
        ]
    )
    await db_session.commit()

    await db_session.delete(project)
    await db_session.commit()

    for model in (AgentRun, ChatMessage, Changeset):
        count = await db_session.scalar(select(func.count()).select_from(model))
        assert count == 0, model.__tablename__
