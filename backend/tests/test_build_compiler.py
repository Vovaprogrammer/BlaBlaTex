"""Сборка против настоящего компилятора из docker compose.

По умолчанию не запускается: в CI компилятора нет, а образ собирается минуты.
Локально — после `docker compose up -d`:

    uv run pytest -m compiler
"""

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
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
from app.modules.builds.dependencies import get_compiler
from app.modules.builds.service import run_build
from app.modules.projects import service as projects_service
from app.modules.projects.models import File, Project
from app.modules.projects.schemas import ProjectCreate

pytestmark = pytest.mark.compiler

# Кириллица и Liberation Serif — то, на чём держатся шаблоны отчётов; картинка и код —
# из материалов (architecture.md 6).
MAIN_TEX = r"""\documentclass{article}
\usepackage{fontspec}
\setmainfont{Liberation Serif}
\usepackage[russian]{babel}
\usepackage{graphicx}
\usepackage{listings}
\begin{document}
\input{sections/intro}
\includegraphics[width=1cm]{materials/pixel.png}
\lstinputlisting{materials/lab.py}
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
    db_session.add(
        File(
            project_id=project.id,
            path="materials/lab.py",
            kind="text",
            role="material",
            content="print(1)\n",
            size=9,
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
    assert (first.pages, first.errors) == (1, [])
    assert calls == ["main.tex"]
    assert (second.status, second.pdf_sha256, second.pages) == ("ok", first.pdf_sha256, 1)


async def test_latex_error_is_build_error_with_log(
    db_session: AsyncSession, storage: LocalStorage, compiler: CompilerClient, lab: Project
) -> None:
    await projects_service.write_text_file(
        db_session, lab.id, "sections/intro.tex", "\\undefinedmacro"
    )

    result = await run_build(db_session, storage, compiler, lab)

    assert (result.status, result.pdf_sha256, result.pages) == ("error", None, None)
    assert result.log_sha256 is not None
    log = await storage.get(result.log_sha256)
    assert b"./sections/intro.tex:1: Undefined control sequence" in log
    # Парсер нашёл ошибку в подключённом файле и показал её место.
    [error] = result.errors
    assert (error["file"], error["line"], error["severity"]) == ("sections/intro.tex", 1, "error")
    assert error["message"] == "Undefined control sequence: \\undefinedmacro"
    assert error["context"] == "> 1 | \\undefinedmacro"


async def test_api_serves_pdf_built_by_real_compiler(
    app: FastAPI,
    user_client: AsyncClient,
    project: dict[str, Any],  # Any — проект как JSON из ответа API
    compiler: CompilerClient,
) -> None:
    app.dependency_overrides[get_compiler] = lambda: compiler
    pid = project["id"]
    doc = "\\documentclass{article}\n\\begin{document}\nПривет, PDF.\n\\end{document}\n"
    written = await user_client.put(f"/api/v1/projects/{pid}/files/main.tex", content=doc)
    assert written.status_code == 201

    started = await user_client.post(f"/api/v1/projects/{pid}/builds")
    build = started.json()
    pdf = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")

    assert started.status_code == 201
    assert (build["status"], build["has_pdf"], build["pages"]) == ("ok", True, 1)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
