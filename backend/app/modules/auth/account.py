"""Удаление аккаунта со всеми данными (architecture.md 9.1, «Удаление аккаунта»).

Данные лежат в таблицах разных модулей; одной транзакцией их удаляет база по внешним
ключам от users (ON DELETE CASCADE), а расход usage остаётся без студента (SET NULL).
Здесь — что база сама не сделает: проверка пароля и прогонов, blob'ы хранилища и журналы
событий в Redis после commit.
"""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, FieldError, field_errors
from app.core.events import EventPublisher
from app.core.storage import Storage
from app.modules.auth import service
from app.modules.auth.models import User
from app.modules.blobs import service as blobs_service
from app.modules.builds import service as builds_service
from app.modules.projects import history
from app.modules.projects import service as projects_service

logger = structlog.get_logger(__name__)

WRONG_PASSWORD_MESSAGE = "Неверный пароль"


def wrong_password() -> service.WrongPasswordError:
    """422 с ошибкой у поля пароля: интерфейс покажет её под полем."""
    error = field_errors(
        [
            FieldError(
                loc=["body", "password"], type="wrong_password", message=WRONG_PASSWORD_MESSAGE
            )
        ]
    )
    return service.WrongPasswordError(error.code, error.message, error.status, error.details)


def project_busy(project: history.OwnedProjectLock) -> AppError:
    """423: ИИ работает в проекте; run_id — чтобы интерфейс мог остановить прогон."""
    return AppError(
        ErrorCode.PROJECT_LOCKED,
        f"ИИ сейчас работает в проекте «{project.title}». "
        "Остановите его и повторите удаление аккаунта",
        423,
        {"run_id": str(project.run_id)},
    )


@dataclass(frozen=True)
class DeletedAccount:
    projects: int
    blobs: blobs_service.Cleanup


async def delete_account(
    session: AsyncSession,
    storage: Storage,
    events: EventPublisher,
    user: User,
    password: str,
) -> DeletedAccount:
    """Удаляет аккаунт со всеми данными. Коммитит сессию.

    Неверный пароль — WrongPasswordError (422); ИИ работает в одном из проектов — 423,
    ничего не удаляется. Сначала commit базы, потом blob'ы и журналы событий: аккаунт
    исчезает сразу и целиком, а что не удалось убрать после commit, уберёт ночная уборка
    хранилища или срок жизни журнала.
    """
    user_id: uuid.UUID = user.id
    ok, _ = await service.verify_password(password, user.password_hash)
    if not ok:
        raise wrong_password()
    # Под блокировкой строк проектов не начнётся ни прогон, ни запись файла: blob'ы,
    # собранные ниже, — все, что есть у студента.
    projects = await history.lock_owner_projects(session, user_id)
    busy = next((project for project in projects if project.run_id is not None), None)
    if busy is not None:
        await session.rollback()
        raise project_busy(busy)
    blobs = await projects_service.owner_blobs(session, user_id)
    blobs |= await builds_service.owner_blobs(session, user_id)
    await service.delete_user(session, user_id)
    await session.commit()

    await events.drop([project.id for project in projects])
    cleanup = await blobs_service.delete_unreferenced(session, storage, blobs)
    # Только id и числа: почты и названий проектов в логе нет.
    logger.info(
        "account_deleted",
        user_id=str(user_id),
        projects=len(projects),
        blobs_deleted=cleanup.deleted,
        blobs_kept=cleanup.kept,
        blobs_failed=cleanup.failed,
    )
    return DeletedAccount(projects=len(projects), blobs=cleanup)
