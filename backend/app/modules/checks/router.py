"""Проверки отчёта (architecture.md 9.1). Логика — в service.py."""

from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.core.db import DbSession, DbSessionmaker
from app.core.http import unless_client_left
from app.core.ratelimit import get_rate_limiter
from app.core.shutdown import ShutdownDep
from app.core.storage import StorageDep
from app.modules.builds.dependencies import ApiCompiler, BuildEnqueue
from app.modules.builds.models import Build
from app.modules.builds.router import BUILDS_LIMIT
from app.modules.checks import service
from app.modules.checks.schemas import CheckResult
from app.modules.projects.dependencies import OwnedProject
from app.modules.templates.dependencies import Templates

router = APIRouter(tags=["checks"])

# Сколько запрос ждёт сборку текущих файлов — как GET /builds/{bid}?wait.
CHECKS_WAIT_MAX_S = 60


@router.post("/projects/{pid}/checks")
async def run_checks(
    request: Request,
    project: OwnedProject,
    session: DbSession,
    sessionmaker: DbSessionmaker,
    storage: StorageDep,
    templates: Templates,
    compiler: ApiCompiler,
    enqueue: BuildEnqueue,
    shutdown: ShutdownDep,
    wait: Annotated[
        int,
        Query(
            ge=0,
            le=CHECKS_WAIT_MAX_S,
            description="Сколько секунд ждать сборку для проверок по PDF, если её ещё нет: "
            f"0–{CHECKS_WAIT_MAX_S}",
        ),
    ] = 0,
) -> CheckResult:
    """Проверки отчёта из docs/checks.md — те, что перечислены в шаблоне проекта.

    Проверки по исходнику — сразу, по текущим файлам. Проверки по PDF читают сборку
    текущих файлов; её нет — ставят сборку и ждут её не дольше wait секунд. Не дождались —
    pdf_checked=false и build_id: повторите запрос. Сборка, которую поставили проверки,
    считается в лимит сборок (60 за 10 минут) — сверх него 429. В проекте ничего не меняется.
    """
    project_id, owner_id = project.id, project.owner_id
    # Дальше база нужна только короткими запросами: соединение запроса возвращаем в пул,
    # иначе каждый ждущий клиент держал бы его до минуты.
    await session.close()

    async def before_build() -> None:
        # Проверки, которым нужна новая сборка, идут в тот же лимит, что POST /builds:
        # иначе лимит сборок обходился бы проверками.
        await get_rate_limiter(request).check("builds", str(owner_id), BUILDS_LIMIT)

    async def guard(waiting: Awaitable[Build | None]) -> Build | None:
        # Сервер останавливается или клиент ушёл — ответ без проверок по PDF.
        return await shutdown.unless_stopped(unless_client_left(request, waiting))

    return await service.run_checks(
        sessionmaker,
        storage,
        templates,
        project_id,
        compiler=compiler,
        enqueue=enqueue,
        wait_s=wait,
        before_build=before_build,
        guard=guard,
    )
