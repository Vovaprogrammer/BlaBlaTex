"""Удаление аккаунта (architecture.md 9.1, «Удаление аккаунта»): данные, пароль, прогоны,
хранилище и журналы событий."""

import hashlib
import uuid
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from app.core.storage import LocalStorage
from app.modules.auth.models import ApiToken, User, UserSession
from app.modules.builds.models import Build
from app.modules.chat.models import AgentRun, ChatMessage
from app.modules.llm import service as llm_service
from app.modules.llm.models import LlmKey, Usage
from app.modules.materials.models import MaterialText
from app.modules.profiles.models import Profile
from app.modules.projects import history
from app.modules.projects.models import Changeset, File, FileRevision, Project
from tests.build_worker import BuildWorker
from tests.fake_events import FakeEvents
from tests.fake_rate_limiter import FakeRateLimiter
from tests.file_samples import JPEG, PNG
from tests.helpers import (
    CSRF,
    PASSWORD,
    STUDENT_EMAIL,
    CreateProject,
    SignIn,
    SignUp,
    backdate_changesets,
)
from tests.test_bearer_auth import issue_token, use_token
from tests.test_builds_api import MAIN_TEX, built, write
from tests.test_chat_api import RunQueue, run_queue, send  # noqa: F401 — фикстура run_queue
from tests.test_uploads import saved, upload

ACCOUNT = "/api/v1/account"
OTHER_EMAIL = "other@example.com"
# Модели, где после удаления не должно остаться строк удалённого студента.
OWNED_MODELS = (
    User,
    UserSession,
    ApiToken,
    Profile,
    LlmKey,
    Project,
    File,
    FileRevision,
    Changeset,
    MaterialText,
    Build,
    ChatMessage,
    AgentRun,
)


async def delete_account(client: AsyncClient, password: str = PASSWORD) -> Response:
    return await client.request("DELETE", ACCOUNT, json={"password": password}, headers=CSRF)


async def counts(session: AsyncSession) -> dict[str, int | None]:
    return {
        model.__name__: await session.scalar(select(func.count()).select_from(model))
        for model in OWNED_MODELS
    }


async def test_deletion_removes_all_data_and_keeps_shared_file(
    app: FastAPI,
    db_client: AsyncClient,
    db_session: AsyncSession,
    sign_up: SignUp,
    sign_in: SignIn,
    create_project: CreateProject,
    build_worker: BuildWorker,
    run_queue: RunQueue,  # noqa: F811 — фикстура из test_chat_api
    events: FakeEvents,
) -> None:
    storage: LocalStorage = app.state.storage
    # Другой студент загрузил ту же картинку: blob у них общий.
    await sign_up(OTHER_EMAIL)
    db_client.headers.update(CSRF)
    other_project = await create_project(title="Чужая ЛР")
    saved(await upload(db_client, other_project, ("scheme.png", PNG)))
    before = await counts(db_session)

    await sign_up(STUDENT_EMAIL)
    project = await create_project()
    pid = project["id"]
    saved(await upload(db_client, project, ("scheme.png", PNG), ("photo.jpg", JPEG)))
    # Повторная загрузка в новом changeset: прежнее фото уходит в историю — ревизия
    # со ссылкой на blob.
    await backdate_changesets(db_session, uuid.UUID(pid))
    await db_session.commit()
    saved(await upload(db_client, project, ("photo.jpg", JPEG + b"\0")))
    await write(db_client, pid, "main.tex", MAIN_TEX)
    build = await built(db_client, build_worker, pid)
    await issue_token(db_client)
    await send(db_client, project, "Сделай отчёт")
    user_id = await db_session.scalar(select(User.id).where(User.email == STUDENT_EMAIL))
    assert user_id is not None
    await llm_service.record_usage(db_session, user_id, None, 100, 50, Decimal("0.01"))
    db_session.add(LlmKey(user_id=user_id, provider="openrouter", encrypted_key="x", last4="abcd"))
    await db_session.commit()
    stored = await db_session.scalar(select(Build).where(Build.id == uuid.UUID(build["id"])))
    assert stored is not None and stored.pdf_sha256 and stored.log_sha256
    own_blobs = [
        hashlib.sha256(JPEG).hexdigest(),
        hashlib.sha256(JPEG + b"\0").hexdigest(),
        stored.pdf_sha256,
        stored.log_sha256,
    ]
    shared_blob = hashlib.sha256(PNG).hexdigest()

    with capture_logs() as logs:
        response = await delete_account(db_client)

    assert response.status_code == 204, response.text
    # Cookie стирается, а не продлевается.
    [cookie] = response.headers.get_list("set-cookie")
    assert cookie.startswith("bbt_session=") and "Max-Age=0" in cookie
    # Строк студента не осталось: всего столько, сколько было до его регистрации.
    assert await counts(db_session) == before
    # Расход остался, но без студента.
    usage = (await db_session.scalars(select(Usage))).all()
    assert [(row.user_id, row.tokens_in, row.tokens_out) for row in usage] == [(None, 100, 50)]
    # Свои файлы студента удалены, общий остался.
    for sha256 in own_blobs:
        assert not await storage.exists(sha256)
    assert await storage.exists(shared_blob)
    assert events.dropped == [uuid.UUID(pid)]
    [log] = [log for log in logs if log["event"] == "account_deleted"]
    assert log["user_id"] == str(user_id)
    assert log["projects"] == 1
    assert log["blobs_kept"] == 1
    assert log["blobs_deleted"] >= len(own_blobs)
    assert STUDENT_EMAIL not in repr(logs)

    # У другого студента картинка открывается.
    await sign_in(OTHER_EMAIL)
    image = await db_client.get(
        f"/api/v1/projects/{other_project['id']}/files/materials/scheme.png"
    )
    assert image.status_code == 200
    assert image.content == PNG


async def test_other_devices_and_tokens_stop_working(
    db_client: AsyncClient, sign_up: SignUp, sign_in: SignIn
) -> None:
    await sign_up(STUDENT_EMAIL)
    first_device = db_client.cookies["bbt_session"]
    await sign_in(STUDENT_EMAIL)
    token = (await issue_token(db_client))["token"]

    assert (await delete_account(db_client)).status_code == 204

    db_client.cookies.clear()
    old_session = await db_client.get(
        "/api/v1/auth/me", headers={"Cookie": f"bbt_session={first_device}"}
    )
    use_token(db_client, token)
    by_token = await db_client.get("/api/v1/auth/me")
    assert old_session.status_code == 401
    assert by_token.status_code == 401


async def test_wrong_password_is_field_error_and_counts_as_login_attempt(
    user_client: AsyncClient, db_session: AsyncSession, rate_limits: FakeRateLimiter
) -> None:
    response = await delete_account(user_client, "wrong-password")

    assert response.status_code == 422
    assert response.json()["error"]["details"] == {
        "errors": [
            {"loc": ["body", "password"], "type": "wrong_password", "message": "Неверный пароль"}
        ]
    }
    [counters] = rate_limits.attempts
    email_key = hashlib.sha256(STUDENT_EMAIL.encode()).hexdigest()
    assert [(c.name, c.key) for c in counters] == [
        ("login_pair", f"{email_key}:127.0.0.1"),
        ("login_ip", "127.0.0.1"),
        ("login_email", email_key),
    ]
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_exhausted_limit_refuses_without_checking_password(
    user_client: AsyncClient, db_session: AsyncSession, rate_limits: FakeRateLimiter
) -> None:
    rate_limits.blocked_retry_after = 600

    response = await delete_account(user_client)

    assert response.status_code == 429
    assert response.json()["error"]["message"] == (
        "Слишком много попыток входа. Повторите через 10 мин"
    )
    assert rate_limits.attempts == []
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_token_cannot_delete_account(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = (await issue_token(user_client))["token"]
    use_token(user_client, token)

    response = await user_client.request("DELETE", ACCOUNT, json={"password": PASSWORD})

    assert response.status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_running_agent_blocks_deletion(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,  # noqa: F811 — фикстура из test_chat_api
    db_session: AsyncSession,
) -> None:
    run = (await send(user_client, project, "Сделай отчёт"))["run"]
    await db_session.execute(update(AgentRun).values(status="running"))
    # Как воркер: идущий прогон держит проект.
    assert await history.take_run_lock(db_session, uuid.UUID(project["id"]), uuid.UUID(run["id"]))
    await db_session.commit()

    response = await delete_account(user_client)

    assert response.status_code == 423
    assert response.json()["error"] == {
        "code": "project_locked",
        "message": (
            "ИИ сейчас работает в проекте «ЛР 1». Остановите его и повторите удаление аккаунта"
        ),
        "details": {"run_id": run["id"]},
    }
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Project)) == 1


async def test_queued_run_is_deleted_with_project(
    user_client: AsyncClient,
    project: dict[str, Any],
    run_queue: RunQueue,  # noqa: F811 — фикстура из test_chat_api
    db_session: AsyncSession,
) -> None:
    await send(user_client, project, "Сделай отчёт")

    response = await delete_account(user_client)

    assert response.status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(AgentRun)) == 0


async def test_deletion_needs_csrf_header(user_client: AsyncClient) -> None:
    response = await user_client.request(
        "DELETE", ACCOUNT, json={"password": PASSWORD}, headers={"X-CSRF-Protection": "0"}
    )

    assert response.status_code == 403
