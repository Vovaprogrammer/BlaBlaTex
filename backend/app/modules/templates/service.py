"""Проекты из шаблонов: поля по манифесту и создание проекта (architecture.md 7, 9.5).

Таблицы проектов и файлов принадлежат модулю projects — сюда только через его сервис.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, field_errors, request_error
from app.modules.projects import service as projects_service
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.templates.manifest import TemplateManifest
from app.modules.templates.registry import Registry

FieldValues = dict[str, str | int]


def validate_fields(manifest: TemplateManifest, values: FieldValues) -> FieldValues:
    """Значения полей проекта, проверенные по манифесту (9.5).

    Неизвестное поле, пропущенное обязательное, значение не того типа или не из options —
    422 с ошибкой на каждое поле: loc = body, fields, ключ. Обязательная строка из одних
    пробелов — как пропущенная. Непереданное поле с default получает default.
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
    """Создаёт проект из шаблона: файлы шаблона, kind, engine, главный файл и версия —
    из манифеста, поля проверены по нему.

    Нет такого шаблона — 422 у template_slug: это поле тела запроса, а не адрес.
    """
    template = templates.get(data.template_slug)
    if template is None:
        raise request_error(["body", "template_slug"], "Такого шаблона нет")
    manifest = template.manifest
    new = projects_service.NewProject(
        title=data.title,
        template_slug=manifest.slug,
        template_version=manifest.version,
        kind=manifest.kind,
        engine=manifest.engine,
        main_file=manifest.main,
        fields=validate_fields(manifest, data.fields),
    )
    return await projects_service.create_project(session, owner_id, new, template.files)


async def update_project(
    session: AsyncSession, project: Project, data: ProjectUpdate, templates: Registry
) -> Project:
    """Меняет название и поля проекта; новые поля проверяются по манифесту его шаблона."""
    if data.fields is not None:
        template = templates.get(project.template_slug)
        if template is None:
            raise request_error(["body", "fields"], "Шаблона проекта больше нет — поля не изменить")
        fields = validate_fields(template.manifest, data.fields)
        data = data.model_copy(update={"fields": fields})
    return await projects_service.update_project(session, project, data)
