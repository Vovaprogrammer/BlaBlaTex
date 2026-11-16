"""План отчёта (architecture.md 8, 9.1 «План отчёта»). Логика — в service.py."""

from fastapi import APIRouter, Request

from app.core.db import DbSession
from app.core.errors import not_implemented
from app.core.events import EventsDep
from app.core.ratelimit import get_rate_limiter
from app.modules.auth.dependencies import CurrentUser
from app.modules.chat import service as chat_service
from app.modules.chat import tasks
from app.modules.chat.dependencies import RunEnqueue
from app.modules.chat.router import MESSAGES_LIMIT
from app.modules.chat.schemas import MessageCreated
from app.modules.llm.dependencies import AppSettings
from app.modules.plans import service
from app.modules.plans.schemas import PlanOut, PlanUpdate
from app.modules.projects.dependencies import OwnedProject
from app.modules.projects.schemas import LOCKED_RESPONSES
from app.modules.templates.dependencies import Templates

router = APIRouter(prefix="/projects", tags=["plans"])

# Сообщения студента, с которых начинаются прогоны плана и отчёта по нему: так в чате
# видно, что попросили, и история агента читается как обычный разговор.
PLAN_REQUEST_TEXT = "Составь план отчёта"


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
async def make_plan(
    project: OwnedProject,
    user: CurrentUser,
    session: DbSession,
    events: EventsDep,
    enqueue: RunEnqueue,
    settings: AppSettings,
    templates: Templates,
    request: Request,
) -> MessageCreated:
    """Сообщение «Составь план отчёта» и прогон kind=plan в очереди — как POST /messages.

    Готовый план придёт событием plan.updated, прежний план остаётся до него. Ошибки — как
    у POST /messages: 423, 429 (квота и лимит сообщений), 500; шаблона проекта нет — 404.
    """
    service.template_sections(project, templates)
    await get_rate_limiter(request).check("messages", str(user.id), MESSAGES_LIMIT)
    created = await tasks.post_message(
        session, events, project, user.id, PLAN_REQUEST_TEXT, settings, enqueue, kind="plan"
    )
    return MessageCreated(
        message=chat_service.message_out(created.message, None),
        run=await chat_service.run_out(session, created.run),
    )


@router.post("/{pid}/plan/confirm", status_code=201, responses=LOCKED_RESPONSES)
async def confirm_plan(project: OwnedProject) -> MessageCreated:
    """Подтверждает план и запускает прогон kind=report: агент пишет отчёт по плану.

    Плана нет — 404; остальные ошибки — как у POST /messages: 423, 429, 500.
    """
    raise not_implemented()
