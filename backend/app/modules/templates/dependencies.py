"""HTTP-часть шаблонов: реестр приложения."""

from typing import Annotated

from fastapi import Depends, Request

from app.modules.templates.registry import Registry


def get_templates(request: Request) -> Registry:
    """Реестр шаблонов; его загружает create_app()."""
    templates: Registry = request.app.state.templates
    return templates


Templates = Annotated[Registry, Depends(get_templates)]
