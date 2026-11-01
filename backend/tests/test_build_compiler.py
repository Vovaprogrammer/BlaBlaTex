"""Сборка против настоящего компилятора из docker compose.

По умолчанию не запускается: в CI компилятора нет, а образ собирается минуты.
Локально — после `docker compose up -d`:

    uv run pytest -m compiler
"""

import base64
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.storage import LocalStorage
from app.modules.auth import service as auth_service
from app.modules.builds.compiler import (
    CompilerClient,
    CompilerError,
    CompileResult,
    create_http_client,
)
from app.modules.builds.service import run_build
from app.modules.projects import service as projects_service
from app.modules.projects.models import File, Project
from app.modules.projects.schemas import ProjectCreate

pytestmark = pytest.mark.compiler

# Кириллица и Liberation Serif — то, на чём держатся шаблоны отчётов; картинка — из материалов.
MAIN_TEX = r"""\documentclass{article}
\usepackage{fontspec}
\setmainfont{Liberation Serif}
\usepackage[russian]{babel}
\usepackage{graphicx}
\begin{document}
\input{sections/intro}
\includegraphics[width=1cm]{materials/pixel.png}
\end{document}
"""
# Картинка 1×1 пиксель.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture
async def compiler() -> AsyncIterator[CompilerClient]:
    url = Settings(app_env="test").compiler_base_url
    async with create_http_client(url) as http:
        client = CompilerClient(http)
        try:
            await client.version()
        except CompilerError:
            pytest.fail(
                f"Компилятор не отвечает на {url}. Запустите docker compose up -d.", pytrace=False
            )
        yield client


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
async def lab(db_session: AsyncSession, storage: LocalStorage) -> Project:
    user, _ = await auth_service.register(db_session, "ivanov@example.com", "password1")
    data = ProjectCreate(title="ЛР 1", template_slug="test-lab", fields={})
    project = await projects_service.create_project(db_session, user.id, data)
    await projects_service.write_text_file(db_session, project.id, "main.tex", MAIN_TEX)
    await projects_service.write_text_file(
        db_session, project.id, "sections/intro.tex", "Съешь же ещё этих мягких французских булок."
    )
    db_session.add(
        File(
            project_id=project.id,
            path="materials/pixel.png",
            kind="binary",
            role="material",
            blob_sha256=await storage.put(PIXEL_PNG),
            size=len(PIXEL_PNG),
        )
    )
    await db_session.commit()
    return project


async def test_project_builds_to_pdf_and_rebuild_comes_from_cache(
    db_session: AsyncSession,
    storage: LocalStorage,
    compiler: CompilerClient,
    lab: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    compile_for_real = compiler.compile

    async def counting_compile(archive: bytes, **kwargs: str) -> CompileResult:
        calls.append(kwargs["main"])
        return await compile_for_real(archive, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(compiler, "compile", counting_compile)

    first = await run_build(db_session, storage, compiler, lab)
    second = await run_build(db_session, storage, compiler, lab)

    assert first.status == "ok", first.errors
    assert first.pdf_sha256 is not None and first.log_sha256 is not None
    assert (await storage.get(first.pdf_sha256)).startswith(b"%PDF")
    assert b"XeTeX" in await storage.get(first.log_sha256)
    assert first.synctex_sha256 is not None
    assert calls == ["main.tex"]
    assert (second.status, second.pdf_sha256) == ("ok", first.pdf_sha256)


async def test_latex_error_is_build_error_with_log(
    db_session: AsyncSession, storage: LocalStorage, compiler: CompilerClient, lab: Project
) -> None:
    await projects_service.write_text_file(
        db_session, lab.id, "sections/intro.tex", "\\undefinedmacro"
    )

    result = await run_build(db_session, storage, compiler, lab)

    assert (result.status, result.pdf_sha256) == ("error", None)
    assert result.log_sha256 is not None
    log = await storage.get(result.log_sha256)
    assert b"./sections/intro.tex:1: Undefined control sequence" in log
