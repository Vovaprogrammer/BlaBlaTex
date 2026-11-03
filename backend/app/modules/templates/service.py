"""Проекты из шаблонов: поля по манифесту, создание проекта и meta.tex (architecture.md 7, 9.5,
9.6).

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
from app.modules.projects.models import File, Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.templates.manifest import MAX_VALUE_LENGTH, TemplateManifest
from app.modules.templates.meta import render_meta
from app.modules.templates.registry import META_FILE, Registry

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
    и meta.tex пересоздаётся с ними в той же транзакции; изменился — вкладкам уходит
    file.changed."""
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
            session, project.id, META_FILE, render_meta(profile, template.manifest, fields)
        )
    project = await projects_service.update_project(session, project, data)
    if meta is not None:
        await projects_service.publish_file_changed(events, meta, author="system")
    return project


async def update_profile(
    session: AsyncSession,
    events: EventPublisher,
    user_id: uuid.UUID,
    data: ProfileUpdate,
    templates: Registry,
) -> Profile:
    """Сохраняет профиль и пересоздаёт meta.tex во всех проектах пользователя — одной
    транзакцией. Вкладкам уходит file.changed по каждому изменившемуся meta.tex.

    Проект, чьего шаблона уже нет в реестре, пропускается: без манифеста не собрать
    макросы его полей.
    """
    profile = await profiles_service.update_profile(session, user_id, data)
    changed: list[File] = []
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
        file = await projects_service.write_generated_file(session, project.id, META_FILE, meta)
        if file is not None:
            changed.append(file)
    await session.commit()
    for file in changed:
        await projects_service.publish_file_changed(events, file, author="system")
    return profile
