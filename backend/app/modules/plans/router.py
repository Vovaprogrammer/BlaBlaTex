"""План отчёта (architecture.md 8, 9.1 «План отчёта»). Логика — в service.py."""

from fastapi import APIRouter

from app.core.db import DbSession
from app.core.errors import not_implemented
from app.core.events import EventsDep
from app.modules.chat.schemas import MessageCreated
from app.modules.plans import service
from app.modules.plans.schemas import PlanOut, PlanUpdate
from app.modules.projects.dependencies import OwnedProject
from app.modules.projects.schemas import LOCKED_RESPONSES
from app.modules.templates.dependencies import Templates

router = APIRouter(prefix="/projects", tags=["plans"])


@router.get("/{pid}/plan")
async def get_plan(project: OwnedProject, session: DbSession, templates: Templates) -> PlanOut:
    """План отчёта проекта: разделы шаблона по порядку, материалы в них и вне плана.

    Плана ещё нет или шаблона проекта больше нет — 404.
    """
    return await service.get_plan(session, project, templates)


@router.put("/{pid}/plan", responses=LOCKED_RESPONSES)
async def update_plan(
    body: PlanUpdate,
    project: OwnedProject,
    session: DbSession,
    events: EventsDep,
    templates: Templates,
) -> PlanOut:
    """Заменяет разделы плана; плана не было — создаёт его. Статус — снова draft.

    Раздела нет в шаблоне или материала нет в materials/ — 422 с местом ошибки; прогон
    проекта идёт или ждёт — 423.
    """
    return await service.update_plan(session, events, project, templates, body)


@router.post("/{pid}/plan", status_code=201, responses=LOCKED_RESPONSES)
async def make_plan(project: OwnedProject) -> MessageCreated:
    """Сообщение «Составь план отчёта» и прогон kind=plan в очереди — как POST /messages.

    Готовый план придёт событием plan.updated. Ошибки — как у POST /messages: 423, 429
    (квота и лимит сообщений), 500.
    """
    raise not_implemented()


@router.post("/{pid}/plan/confirm", status_code=201, responses=LOCKED_RESPONSES)
async def confirm_plan(project: OwnedProject) -> MessageCreated:
    """Подтверждает план и запускает прогон kind=report: агент пишет отчёт по плану.

    Плана нет — 404; остальные ошибки — как у POST /messages: 423, 429, 500.
    """
    raise not_implemented()
