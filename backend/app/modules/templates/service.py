"""Проекты из шаблонов: поля по манифесту, создание проекта, meta.tex и шаблон для агента
(architecture.md 7, 9.4, 9.5, 9.6).

Таблицы проектов, файлов и профилей принадлежат модулям projects и profiles — сюда только
через их сервисы. meta.tex пересоздаётся при изменении полей проекта или профиля в той же
транзакции, что и само изменение: данные и meta.tex не разойдутся.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, field_errors, request_error
from app.core.events import EventPublisher
from app.modules.profiles import service as profiles_service
from app.modules.profiles.models import Profile
from app.modules.profiles.schemas import ProfileUpdate
from app.modules.projects import service as projects_service
from app.modules.projects.history import ProjectChange, Writer
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.projects.tools import GuideField, TemplateGuide, TemplateMacro
from app.modules.templates.manifest import MAX_VALUE_LENGTH, TemplateManifest, macro_suffix
from app.modules.templates.meta import render_meta
from app.modules.templates.registry import META_FILE, Registry
from app.modules.templates.schemas import TemplateSection

logger = structlog.get_logger(__name__)

FieldValues = dict[str, str | int]


def validate_fields(manifest: TemplateManifest, values: FieldValues) -> FieldValues:
    """Значения полей проекта, проверенные по манифесту (9.5).

    Неизвестное поле, пропущенное обязательное, значение не того типа, длиннее лимита
    своего типа или не из options — 422 с ошибкой на каждое поле: loc = body, fields, ключ.
    Обязательная строка из одних пробелов — как пропущенная. Непереданное поле с default
    получает default.
    """
    errors: list[FieldError] = []

    def error(key: str, kind: str, message: str) -> None:
        errors.append(FieldError(loc=["body", "fields", key], type=kind, message=message))

    known = {field.key for field in manifest.fields}
    for key in values:
        if key not in known:
            error(key, "extra_forbidden", "Такого поля нет в шаблоне")
    checked: FieldValues = {}
    for field in manifest.fields:
        if field.key not in values:
            if field.default is not None:
                checked[field.key] = field.default
            elif field.required:
                error(field.key, "missing", "Обязательное поле")
            continue
        value = values[field.key]
        if field.type == "int":
            # bool в Python — тоже int. Схема запроса его отвергает, но сервис вызывают
            # не только из HTTP.
            if isinstance(value, bool) or not isinstance(value, int):
                error(field.key, "int_type", "Ожидается целое число")
                continue
        elif not isinstance(value, str):
            error(field.key, "string_type", "Ожидается строка")
            continue
        elif len(value) > (limit := MAX_VALUE_LENGTH[field.type]):
            error(field.key, "string_too_long", f"Максимальная длина — {limit}")
            continue
        elif field.required and not value.strip():
            error(field.key, "missing", "Обязательное поле")
            continue
        elif field.type == "select" and value not in field.options:
            error(
                field.key,
                "literal_error",
                f"Выберите один из вариантов: {', '.join(field.options)}",
            )
            continue
        checked[field.key] = value
    if errors:
        raise field_errors(errors)
    return checked


# Макросы класса mtuci-report из 9.6 — их агент вставляет в отчёт (get_template_guide).
CLASS_MACROS = (
    TemplateMacro(
        usage="\\bbtTitlePage",
        description="Титульный лист из данных профиля и полей проекта",
    ),
    TemplateMacro(
        usage="\\bbtScreenshot[width]{path}{caption}{label}",
        description="Рисунок с подписью «Рисунок N — caption»",
    ),
    TemplateMacro(
        usage="\\bbtCodeFile[language]{path}{caption}{label}",
        description="Листинг из файла проекта, например из materials/",
    ),
    TemplateMacro(
        usage="\\begin{bbtcode}{language}{caption}{label} ... \\end{bbtcode}",
        description="Листинг текстом прямо в отчёте",
    ),
    TemplateMacro(
        usage="\\begin{bbttable}{caption}{label} \\begin{tabular}...\\end{tabular} \\end{bbttable}",
        description="Таблица с подписью «Таблица N — caption», внутри обычный tabular",
    ),
)


def template_guide(manifest: TemplateManifest, values: FieldValues) -> TemplateGuide:
    """Что агенту нужно знать о шаблоне проекта (9.4): разделы, правила, поля проекта
    с их значениями и макросами, макросы класса."""
    return TemplateGuide(
        slug=manifest.slug,
        title=manifest.title,
        discipline=manifest.discipline,
        main_file=manifest.main,
        sections=[
            TemplateSection.model_validate(section, from_attributes=True)
            for section in manifest.sections
        ],
        ai_rules=manifest.ai_rules,
        fields=[
            GuideField(
                key=field.key,
                label=field.label,
                value=values.get(field.key),
                macro=f"\\bbt{macro_suffix(field.key)}",
            )
            for field in manifest.fields
        ],
        # Копии: правка результата не должна менять макросы для следующих вызовов.
        macros=[macro.model_copy() for macro in CLASS_MACROS],
    )


async def create_project(
    session: AsyncSession, owner_id: uuid.UUID, data: ProjectCreate, templates: Registry
) -> Project:
    """Создаёт проект из шаблона: файлы шаблона и meta.tex из профиля и полей; kind, engine,
    главный файл и версия — из манифеста, поля проверены по нему.

    Нет такого шаблона — 422 у template_slug: это поле тела запроса, а не адрес.
    """
    template = templates.get(data.template_slug)
    if template is None:
        raise request_error(["body", "template_slug"], "Такого шаблона нет")
    manifest = template.manifest
    fields = validate_fields(manifest, data.fields)
    new = projects_service.NewProject(
        title=data.title,
        template_slug=manifest.slug,
        template_version=manifest.version,
        kind=manifest.kind,
        engine=manifest.engine,
        main_file=manifest.main,
        fields=fields,
    )
    # Профиль блокируется до коммита: параллельная правка профиля дождётся нового проекта
    # и перепишет его meta.tex, а не пропустит его.
    profile = await profiles_service.get_profile(session, owner_id, lock=True)
    meta = render_meta(profile, manifest, fields)
    return await projects_service.create_project(
        session, owner_id, new, template.files, generated={META_FILE: meta}
    )


async def update_project(
    session: AsyncSession,
    events: EventPublisher,
    project: Project,
    data: ProjectUpdate,
    templates: Registry,
) -> Project:
    """Меняет название и поля проекта. Новые поля проверяются по манифесту его шаблона,
    и meta.tex пересоздаётся с ними в той же транзакции — правкой author=system от имени
    владельца; изменился — вкладкам уходит file.changed."""
    meta = None
    if data.fields is not None:
        template = templates.get(project.template_slug)
        if template is None:
            raise request_error(["body", "fields"], "Шаблона проекта больше нет — поля не изменить")
        fields = validate_fields(template.manifest, data.fields)
        data = data.model_copy(update={"fields": fields})
        # Сначала профиль, потом проект — тот же порядок блокировок, что у правки профиля.
        profile = await profiles_service.get_profile(session, project.owner_id, lock=True)
        meta = await projects_service.write_generated_file(
            session,
            Writer(events, "system", project.owner_id),
            project.id,
            META_FILE,
            render_meta(profile, template.manifest, fields),
        )
    project = await projects_service.update_project(session, project, data)
    if meta is not None:
        await meta.publish()
    return project


async def update_profile(
    session: AsyncSession,
    events: EventPublisher,
    user_id: uuid.UUID,
    data: ProfileUpdate,
    templates: Registry,
) -> Profile:
    """Сохраняет профиль и пересоздаёт meta.tex во всех проектах пользователя — одной
    транзакцией. В каждом проекте, где meta.tex изменился, это свой changeset author=system,
    и вкладкам уходит file.changed.

    Проект, чьего шаблона уже нет в реестре, пропускается: без манифеста не собрать
    макросы его полей.
    """
    profile = await profiles_service.update_profile(session, user_id, data)
    writer = Writer(events, "system", user_id)
    changed: list[ProjectChange] = []
    for project in await projects_service.list_projects(session, user_id):
        template = templates.get(project.template_slug)
        if template is None:
            logger.warning(
                "meta_skipped_unknown_template",
                project_id=str(project.id),
                template_slug=project.template_slug,
            )
            continue
        meta = render_meta(profile, template.manifest, project.fields)
        change = await projects_service.write_generated_file(
            session, writer, project.id, META_FILE, meta
        )
        if change is not None:
            changed.append(change)
    await session.commit()
    for change in changed:
        await change.publish()
    return profile
