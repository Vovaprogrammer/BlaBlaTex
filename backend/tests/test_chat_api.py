"""API чата (architecture.md 9.1): сообщение с прогоном в очереди, история по страницам,
прогон, который идёт сейчас, и второй прогон при активном."""

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq.exceptions import SendTaskError

from app.modules.chat.dependencies import get_run_enqueue
from app.modules.chat.models import AgentRun, ChatMessage
from app.modules.chat.schemas import MESSAGE_MAX_LENGTH
from app.modules.projects import history
from app.modules.projects.models import Changeset
from tests.helpers import CreateProject, SignUp


class RunQueue:
    """Очередь прогонов в тесте: запоминает, какие прогоны отправлены воркеру."""

    def __init__(self) -> None:
        self.run_ids: list[uuid.UUID] = []
        self.error: Exception | None = None

    async def enqueue(self, run_id: uuid.UUID) -> None:
        if self.error is not None:
            raise self.error
        self.run_ids.append(run_id)


@pytest.fixture
def run_queue(app: FastAPI) -> RunQueue:
    queue = RunQueue()
    app.dependency_overrides[get_run_enqueue] = lambda: queue.enqueue
    return queue


def messages_url(project: dict[str, Any]) -> str:
    return f"/api/v1/projects/{project['id']}/messages"


async def send(client: AsyncClient, project: dict[str, Any], text: str) -> dict[str, Any]:
    response = await client.post(messages_url(project), json={"text": text})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def finish_runs(session: AsyncSession) -> None:
    """Прогоны этого теста закончены: можно отправить следующее сообщение."""
    await session.execute(update(AgentRun).values(status="done"))
    await session.commit()


async def test_post_message_creates_queued_run(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,
    db_session: AsyncSession,
) -> None:
    body = await send(user_client, project, "  Сделай отчёт по ЛР 3\n")

    message, run = body["message"], body["run"]
    assert message["role"] == "user"
    assert message["status"] is None
    # Пробелы по краям не сохраняются.
    assert message["parts"] == [{"type": "text", "text": "Сделай отчёт по ЛР 3"}]
    assert (message["run_id"], message["seq"]) == (run["id"], 0)
    assert run["status"] == "queued"
    assert (run["error"], run["finished_at"]) == (None, None)
    assert run_queue.run_ids == [uuid.UUID(run["id"])]
    changeset = await db_session.get(Changeset, uuid.UUID(run["changeset_id"]))
    assert changeset is not None
    assert (changeset.author, str(changeset.run_id)) == ("ai", run["id"])


async def test_get_messages_shows_reply_and_active_run(
    user_client: AsyncClient, project: dict[str, Any], run_queue: RunQueue
) -> None:
    body = await send(user_client, project, "Привет")

    response = await user_client.get(messages_url(project))

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["has_more"] is False
    assert page["active_run"] == body["run"]
    user, reply = page["items"]
    assert user == body["message"]
    assert reply["id"] == body["run"]["message_id"]
    assert (reply["role"], reply["status"], reply["parts"], reply["seq"]) == (
        "assistant",
        "queued",
        [],
        0,
    )
    assert reply["run_id"] == body["run"]["id"]


async def test_finished_run_is_not_active(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,
    db_session: AsyncSession,
) -> None:
    await send(user_client, project, "Привет")
    await finish_runs(db_session)

    page = (await user_client.get(messages_url(project))).json()

    assert page["active_run"] is None
    assert [item["status"] for item in page["items"]] == [None, "done"]


@pytest.mark.parametrize(
    ("text", "error_type"),
    [
        ("   \n", "string_too_short"),
        ("я" * (MESSAGE_MAX_LENGTH + 1), "string_too_long"),
        ("до\x00после", "nul_character"),
    ],
)
async def test_bad_text_is_rejected(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,
    db_session: AsyncSession,
    text: str,
    error_type: str,
) -> None:
    response = await user_client.post(messages_url(project), json={"text": text})

    assert response.status_code == 422
    [error] = response.json()["error"]["details"]["errors"]
    assert (error["loc"], error["type"]) == (["body", "text"], error_type)
    assert run_queue.run_ids == []
    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 0


async def test_longest_text_is_accepted(
    user_client: AsyncClient, project: dict[str, Any], run_queue: RunQueue
) -> None:
    body = await send(user_client, project, "я" * MESSAGE_MAX_LENGTH)

    assert len(body["message"]["parts"][0]["text"]) == MESSAGE_MAX_LENGTH


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_second_message_while_run_is_active_is_locked(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,
    db_session: AsyncSession,
    status: str,
) -> None:
    first = await send(user_client, project, "Первое")
    await db_session.execute(update(AgentRun).values(status=status))
    if status == "running":
        # Как воркер: идущий прогон держит проект.
        run_id = uuid.UUID(first["run"]["id"])
        assert await history.take_run_lock(db_session, uuid.UUID(project["id"]), run_id)
    await db_session.commit()

    response = await user_client.post(messages_url(project), json={"text": "Второе"})

    assert response.status_code == 423
    error = response.json()["error"]
    assert error["code"] == "project_locked"
    assert error["details"] == {"run_id": first["run"]["id"]}
    assert len(run_queue.run_ids) == 1
    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 2


async def test_queue_unavailable_saves_nothing(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,
    db_session: AsyncSession,
) -> None:
    run_queue.error = SendTaskError()

    response = await user_client.post(messages_url(project), json={"text": "Привет"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal"
    for model in (ChatMessage, AgentRun):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    ai_changesets = select(func.count()).select_from(Changeset).where(Changeset.author == "ai")
    assert await db_session.scalar(ai_changesets) == 0
    # Проект не заблокирован: можно отправить снова.
    run_queue.error = None
    await send(user_client, project, "Привет")


async def test_slow_queue_is_unavailable(
    app: FastAPI,
    user_client: AsyncClient,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hang(run_id: uuid.UUID) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr("app.modules.chat.tasks.ENQUEUE_TIMEOUT_S", 0.05)
    app.dependency_overrides[get_run_enqueue] = lambda: hang

    response = await user_client.post(messages_url(project), json={"text": "Привет"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal"


async def test_history_pages_from_newest(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,
    db_session: AsyncSession,
) -> None:
    for number in range(3):
        await send(user_client, project, f"Вопрос {number}")
        await finish_runs(db_session)

    first = (await user_client.get(messages_url(project), params={"limit": 4})).json()
    second = (
        await user_client.get(
            messages_url(project), params={"limit": 4, "before": first["items"][0]["id"]}
        )
    ).json()

    def texts(page: dict[str, Any]) -> list[str]:
        return [item["parts"][0]["text"] if item["parts"] else "—" for item in page["items"]]

    assert (texts(first), first["has_more"]) == (["Вопрос 1", "—", "Вопрос 2", "—"], True)
    assert (texts(second), second["has_more"]) == (["Вопрос 0", "—"], False)


async def test_unknown_before_is_validation_error(
    user_client: AsyncClient, project: dict[str, Any]
) -> None:
    response = await user_client.get(messages_url(project), params={"before": str(uuid.uuid4())})

    assert response.status_code == 422
    [error] = response.json()["error"]["details"]["errors"]
    assert error["loc"] == ["query", "before"]


async def test_foreign_project_chat_is_not_found(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,
    sign_up: SignUp,
    create_project: CreateProject,
) -> None:
    mine = await send(user_client, project, "Привет")
    await sign_up("petrov@example.com")
    other = await create_project()

    assert (await user_client.get(messages_url(project))).status_code == 404
    response = await user_client.post(messages_url(project), json={"text": "Чужой"})
    assert response.status_code == 404
    assert run_queue.run_ids == [uuid.UUID(mine["run"]["id"])]
    # Сообщение из чужого чата как before в своём — такого сообщения в чате нет.
    response = await user_client.get(messages_url(other), params={"before": mine["message"]["id"]})
    assert response.status_code == 422


async def test_slow_queue_that_delivered_keeps_message(
    app: FastAPI,
    user_client: AsyncClient,
    project: dict[str, Any],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def deliver_late(run_id: uuid.UUID) -> None:
        # Задание дошло, и воркер взял прогон, а ответ очереди опоздал.
        await db_session.execute(
            update(AgentRun).where(AgentRun.id == run_id).values(status="running")
        )
        await db_session.commit()
        await asyncio.sleep(10)

    monkeypatch.setattr("app.modules.chat.tasks.ENQUEUE_TIMEOUT_S", 0.5)
    app.dependency_overrides[get_run_enqueue] = lambda: deliver_late

    response = await user_client.post(messages_url(project), json={"text": "Привет"})

    # Идущий прогон не удаляется: воркер держал бы проект прогоном, которого нет.
    assert response.status_code == 201, response.text
    run = await db_session.get(AgentRun, uuid.UUID(response.json()["run"]["id"]))
    assert run is not None
    assert run.status == "running"
    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 2
