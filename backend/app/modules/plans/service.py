"""План отчёта (architecture.md 5, 8, 9.1 «План отчёта»): чтение, правка студентом,
подтверждение.

Хранятся только разделы {section_id, materials, note}. Названия, порядок разделов и
материалы вне плана считаются при каждом чтении по шаблону проекта и материалам на этот
момент (build_plan): переименованный раздел шаблона и новый материал видны сразу.
"""

import dataclasses
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, FieldError, field_errors
from app.core.events import EventPublisher, EventType, PlanUpdatedData
from app.modules.chat import service as chat_service
from app.modules.plans.models import ReportPlanRow
from app.modules.plans.schemas import (
    NOTE_MAX_LENGTH,
    PlanOut,
    PlanSection,
    PlanStatus,
    PlanUpdate,
    ReportPlan,
)
from app.modules.projects import history
from app.modules.projects import service as projects_service
from app.modules.projects.models import Project
from app.modules.templates import service as templates_service
from app.modules.templates.manifest import ManifestSection
from app.modules.templates.registry import Registry

PLAN_NOT_FOUND_MESSAGE = "План ещё не составлен"
UNKNOWN_SECTION_MESSAGE = "Такого раздела нет в шаблоне"
REPEATED_SECTION_MESSAGE = "Раздел уже есть в плане"
UNKNOWN_MATERIAL_MESSAGE = "Такого материала нет в папке materials"
REPEATED_MATERIAL_MESSAGE = "Материал уже есть в этом разделе"
# Время записи плана — по часам базы в момент записи, а не начала транзакции (now()) и не
# сервера API: запрос, который ждал блокировку проекта, не получит время раньше записи,
# которую он ждал, и updated_at в plan.updated только растёт.
_CLOCK = func.clock_timestamp()


class SectionInfo(Protocol):
    """Раздел шаблона: из манифеста (ManifestSection) или справки агента (TemplateSection)."""

    @property
    def id(self) -> str: ...

    @property
    def title(self) -> str: ...


@dataclasses.dataclass(frozen=True)
class Confirmation:
    """Подтверждение плана: прежние статус и время — чтобы вернуть их, если прогон report
    не ушёл в очередь, — и время подтверждения."""

    status: PlanStatus
    updated_at: datetime
    confirmed_at: datetime


class StoredSection(BaseModel):
    """Раздел плана, как он лежит в report_plans.plan."""

    section_id: str
    materials: list[str]
    note: str


def template_sections(project: Project, templates: Registry) -> list[ManifestSection]:
    """Разделы шаблона проекта по порядку. Шаблона больше нет — 404, как у справки шаблона."""
    template = templates.get(project.template_slug)
    if template is None:
        raise AppError(ErrorCode.NOT_FOUND, templates_service.TEMPLATE_GONE_MESSAGE, 404)
    return list(template.manifest.sections)


async def material_paths(session: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """Пути материалов проекта (файлы в materials/) по алфавиту."""
    files = await projects_service.list_material_files(session, project_id)
    return [file.path for file in files]


def build_plan(
    stored: Iterable[StoredSection],
    sections: Sequence[SectionInfo],
    materials: Sequence[str],
) -> ReportPlan:
    """План для API и агента из сохранённых разделов, шаблона и материалов сейчас.

    Разделы — все разделы шаблона в его порядке; сохранённого нет — раздел пустой, раздела
    нет в шаблоне — он выпадает. Материалы — только существующие, без повторов в разделе;
    unassigned — материалы, которых нет ни в одном разделе. Из повторов раздела берётся
    первый: так же приводится и план, который вернула модель.
    """
    saved: dict[str, StoredSection] = {}
    for section in stored:
        saved.setdefault(section.section_id, section)
    existing = set(materials)
    used: set[str] = set()
    result = []
    for section in sections:
        source = saved.get(section.id)
        paths = (
            [] if source is None else [p for p in dict.fromkeys(source.materials) if p in existing]
        )
        used.update(paths)
        result.append(
            PlanSection(
                section_id=section.id,
                title=section.title,
                materials=paths,
                note="" if source is None else source.note[:NOTE_MAX_LENGTH],
            )
        )
    return ReportPlan(sections=result, unassigned=[path for path in materials if path not in used])


def stored_sections(plan: ReportPlan) -> list[StoredSection]:
    """Что из плана сохраняется: title и unassigned считаются при чтении."""
    return [
        StoredSection(section_id=section.section_id, materials=section.materials, note=section.note)
        for section in plan.sections
    ]


def plan_ready_text(plan: ReportPlan) -> str:
    """Ответ ассистента после прогона plan: что получилось и что делать дальше."""
    return (
        f"План отчёта готов. Разделов: {len(plan.sections)}, материалов вне плана: "
        f"{len(plan.unassigned)}. Проверьте план, поправьте, если нужно, и нажмите "
        "«Подтвердить» — тогда ИИ напишет отчёт по нему."
    )


async def save_generated(session: AsyncSession, project_id: uuid.UUID, plan: ReportPlan) -> PlanOut:
    """План, который составил прогон plan, — черновиком вместо прежнего. Не коммитит: план
    пишется в одной транзакции с итогом прогона. plan уже приведён к шаблону (build_plan)."""
    row = await _save(session, project_id, stored_sections(plan), "draft")
    return PlanOut(plan=plan, status=row.status, updated_at=row.updated_at)


async def get_plan(session: AsyncSession, project: Project, templates: Registry) -> PlanOut:
    """План проекта для GET /plan. Плана нет или шаблона проекта больше нет — 404."""
    sections = template_sections(project, templates)
    row = await session.get(ReportPlanRow, project.id)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, PLAN_NOT_FOUND_MESSAGE, 404)
    return await _plan_out(session, row, sections)


async def update_plan(
    session: AsyncSession,
    events: EventPublisher,
    project: Project,
    templates: Registry,
    body: PlanUpdate,
) -> PlanOut:
    """Заменяет разделы плана студентом (PUT /plan); плана не было — создаёт. Коммитит.

    Статус — снова draft: изменённый план нужно подтвердить заново. Прогон проекта идёт или
    ждёт — 423: прогон report получает тот план, который студент подтвердил. Раздела нет в
    шаблоне, материала нет в materials/ или они повторяются — 422 с местом ошибки.
    """
    project_id = project.id
    sections = template_sections(project, templates)
    await ensure_no_run(session, project_id)
    # Материалы — уже под блокировкой строки проекта: правка файлов ждёт её, и проверенный
    # список не устареет до commit.
    materials = await material_paths(session, project_id)
    errors = _check_update(body, sections, set(materials))
    if errors:
        raise field_errors(errors)
    stored = [
        StoredSection(section_id=item.section_id, materials=item.materials, note=item.note)
        for item in body.sections
    ]
    row = await _save(session, project_id, stored, "draft")
    out = await _plan_out(session, row, sections, materials)
    await session.commit()
    await publish_updated(events, project_id, out.status, out.updated_at)
    return out


async def confirm_plan(session: AsyncSession, project_id: uuid.UUID) -> Confirmation:
    """Ставит плану статус confirmed. Не коммитит: в той же транзакции создаётся прогон
    report (9.1, «Подтвердить»). Возвращает прежние статус и время — для undo_confirm.

    Плана нет — 404; прогон проекта идёт или ждёт — 423.
    """
    await ensure_no_run(session, project_id)
    row = await session.get(ReportPlanRow, project_id, with_for_update=True, populate_existing=True)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, PLAN_NOT_FOUND_MESSAGE, 404)
    previous_status, previous_updated_at = row.status, row.updated_at
    confirmed_at = await session.scalar(
        update(ReportPlanRow)
        .where(ReportPlanRow.project_id == project_id)
        .values(status="confirmed", updated_at=_CLOCK)
        .returning(ReportPlanRow.updated_at)
    )
    if confirmed_at is None:
        raise RuntimeError(f"План проекта {project_id} не подтверждён")
    return Confirmation(
        status=previous_status, updated_at=previous_updated_at, confirmed_at=confirmed_at
    )


async def undo_confirm(
    session: AsyncSession, project_id: uuid.UUID, confirmation: Confirmation
) -> None:
    """Возвращает плану прежний статус: прогон report не ушёл в очередь (9.1). Не коммитит:
    идёт в одной транзакции с удалением прогона.

    План с тех пор изменили (его updated_at уже другой) — ничего не меняется.
    """
    await session.execute(
        update(ReportPlanRow)
        .where(
            ReportPlanRow.project_id == project_id,
            ReportPlanRow.updated_at == confirmation.confirmed_at,
        )
        .values(status=confirmation.status, updated_at=confirmation.updated_at)
    )


async def plan_for_run(
    session: AsyncSession, project_id: uuid.UUID, templates: Registry
) -> ReportPlan | None:
    """Подтверждённый план для прогона report (RunRequest.plan) — как его видит студент.
    Плана нет, он не подтверждён или шаблона проекта больше нет — None."""
    row = await session.get(ReportPlanRow, project_id)
    project = await projects_service.get_project(session, project_id)
    if row is None or row.status != "confirmed" or project is None:
        return None
    template = templates.get(project.template_slug)
    if template is None:
        return None
    out = await _plan_out(session, row, template.manifest.sections)
    return out.plan


async def ensure_no_run(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Блокирует строку проекта до commit и проверяет, что у проекта нет прогона в очереди
    или идущего: правки плана и подтверждение идут по очереди с запуском прогона. Есть —
    423 с его id."""
    # FOR NO KEY UPDATE: правки плана и подтверждение идут по очереди, а вставка прогона
    # в соседнем запросе не ждёт этой блокировки и не попадает с ней во взаимное ожидание.
    await history.ensure_unlocked(session, project_id, key_share=True)
    active = await chat_service.find_active_run(session, project_id)
    if active is not None:
        raise history.project_locked(active.id)


async def publish_updated(
    events: EventPublisher, project_id: uuid.UUID, status: PlanStatus, updated_at: datetime
) -> None:
    """plan.updated после commit: вкладки перезапрашивают GET /plan."""
    await events.publish(
        project_id,
        EventType.PLAN_UPDATED,
        PlanUpdatedData(status=status, updated_at=updated_at),
    )


async def _save(
    session: AsyncSession,
    project_id: uuid.UUID,
    sections: Sequence[StoredSection],
    status: PlanStatus,
) -> ReportPlanRow:
    """Записывает разделы и статус плана: новый план заменяет прежний. Не коммитит.

    Проект удалили между проверкой и записью — 404.
    """
    plan = {"sections": [section.model_dump(mode="json") for section in sections]}
    statement = (
        insert(ReportPlanRow)
        .values(
            project_id=project_id,
            plan=plan,
            status=status,
            created_at=_CLOCK,
            updated_at=_CLOCK,
        )
        .on_conflict_do_update(
            index_elements=[ReportPlanRow.project_id],
            set_={"plan": plan, "status": status, "updated_at": _CLOCK},
        )
        .returning(ReportPlanRow)
        .execution_options(populate_existing=True)
    )
    try:
        row = await session.scalar(statement)
    except IntegrityError:
        await session.rollback()
        raise AppError(
            ErrorCode.NOT_FOUND, projects_service.PROJECT_NOT_FOUND_MESSAGE, 404
        ) from None
    if row is None:
        raise RuntimeError(f"План проекта {project_id} не записан")
    return row


async def _plan_out(
    session: AsyncSession,
    row: ReportPlanRow,
    sections: Sequence[ManifestSection],
    materials: Sequence[str] | None = None,
) -> PlanOut:
    if materials is None:
        materials = await material_paths(session, row.project_id)
    stored = [StoredSection.model_validate(item) for item in row.plan["sections"]]
    return PlanOut(
        plan=build_plan(stored, sections, materials),
        status=row.status,
        updated_at=row.updated_at,
    )


def _check_update(
    body: PlanUpdate, sections: Sequence[ManifestSection], materials: set[str]
) -> list[FieldError]:
    """Ошибки PUT /plan по полям: разделы — из шаблона и по разу, материалы — из materials/
    и по разу в разделе."""
    known = {section.id for section in sections}
    errors: list[FieldError] = []
    seen_sections: set[str] = set()

    def error(loc: list[str | int], message: str) -> None:
        errors.append(
            FieldError(loc=["body", "sections", *loc], type="value_error", message=message)
        )

    for index, section in enumerate(body.sections):
        if section.section_id not in known:
            error([index, "section_id"], UNKNOWN_SECTION_MESSAGE)
        elif section.section_id in seen_sections:
            error([index, "section_id"], REPEATED_SECTION_MESSAGE)
        seen_sections.add(section.section_id)
        seen_materials: set[str] = set()
        for position, path in enumerate(section.materials):
            if path not in materials:
                error([index, "materials", position], UNKNOWN_MATERIAL_MESSAGE)
            elif path in seen_materials:
                error([index, "materials", position], REPEATED_MATERIAL_MESSAGE)
            seen_materials.add(path)
    return errors
