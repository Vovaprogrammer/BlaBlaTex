"""Проверки отчёта (architecture.md 9.1). Логика — в service.py."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.errors import not_implemented
from app.modules.checks.schemas import CheckResult
from app.modules.projects.dependencies import OwnedProject

router = APIRouter(tags=["checks"])

# Сколько запрос ждёт сборку текущих файлов — как GET /builds/{bid}?wait.
CHECKS_WAIT_MAX_S = 60


@router.post("/projects/{pid}/checks")
async def run_checks(
    project: OwnedProject,
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
    raise not_implemented()
