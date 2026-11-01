"""HTTP-часть сборок: клиент компилятора приложения."""

from typing import Annotated

from fastapi import Depends, Request

from app.modules.builds.compiler import CompilerClient


def get_compiler(request: Request) -> CompilerClient:
    """Клиент компилятора; его создаёт lifespan из create_app()."""
    compiler: CompilerClient | None = getattr(request.app.state, "compiler", None)
    if compiler is None:
        raise RuntimeError(
            "Нет клиента компилятора: lifespan приложения не запущен. "
            "В тестах — подмена get_compiler."
        )
    return compiler


Compiler = Annotated[CompilerClient, Depends(get_compiler)]
