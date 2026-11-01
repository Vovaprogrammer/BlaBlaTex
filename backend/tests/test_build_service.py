"""Сборка без HTTP: что уходит в компилятор, что сохраняется, кэш и проверки проекта.

Компилятор подменён (tests/fake_compiler.py), Storage — во временной папке.
"""

import hashlib
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.storage import LocalStorage
from app.modules.auth import service as auth_service
from app.modules.builds import service as builds_service
from app.modules.builds.models import Build
from app.modules.builds.service import BuildInput, inputs_hash, pack_project, run_build
from app.modules.projects import service as projects_service
from app.modules.projects.models import File, Project
from app.modules.projects.schemas import FileRole, ProjectCreate
from tests.fake_compiler import (
    LOG,
    PDF,
    SYNCTEX,
    VERSION,
    CompileRequest,
    FakeCompiler,
    ok_result,
)

MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nПривет\n\\end{document}\n"
PNG = b"\x89PNG\r\n\x1a\nfake image"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def fake() -> FakeCompiler:
    return FakeCompiler()


@pytest.fixture
async def lab(db_session: AsyncSession) -> Project:
    """Проект с одним main.tex."""
    user, _ = await auth_service.register(db_session, "ivanov@example.com", "password1")
    data = ProjectCreate(title="ЛР 1", template_slug="test-lab", fields={})
    project = await projects_service.create_project(db_session, user.id, data)
    await projects_service.write_text_file(db_session, project.id, "main.tex", MAIN_TEX)
    return project


async def add_file(
    session: AsyncSession,
    storage: LocalStorage,
    project: Project,
    path: str,
    data: str | bytes,
    role: FileRole = "source",
) -> None:
    """Файл с любой ролью; бинарный — как его сохранит загрузка (B2.2): байты в Storage."""
    if isinstance(data, str):
        file = File(kind="text", content=data, size=len(data.encode()))
    else:
        file = File(kind="binary", blob_sha256=await storage.put(data), size=len(data))
    file.project_id, file.path, file.role = project.id, path, role
    session.add(file)
    await session.commit()


async def build(
    session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, project: Project
) -> Build:
    return await run_build(session, storage, fake.client(), project)


async def builds_count(session: AsyncSession, project: Project) -> int:
    count = await session.scalar(
        select(func.count()).select_from(Build).where(Build.project_id == project.id)
    )
    return count or 0


# Что уходит в компилятор.


async def test_archive_has_project_and_materials_except_documents(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await add_file(db_session, storage, lab, "sections/intro.tex", "Введение")
    await add_file(db_session, storage, lab, "figures/plot.pdf", b"%PDF figure")
    await add_file(
        db_session, storage, lab, "meta.tex", "\\newcommand{\\bbtGroup}{БВТ}", "generated"
    )
    await add_file(db_session, storage, lab, "materials/scheme.png", PNG, "material")
    await add_file(db_session, storage, lab, "materials/PHOTO.JPG", b"jpeg", "material")
    await add_file(db_session, storage, lab, "materials/lab.py", "print(1)", "material")
    # Методичку, задание и прочие документы из материалов читает только ИИ (architecture.md 6).
    await add_file(db_session, storage, lab, "materials/method.pdf", b"%PDF", "material")
    await add_file(db_session, storage, lab, "materials/task.DOCX", b"PK", "material")
    await add_file(db_session, storage, lab, "materials/slides.pptx", b"PK", "material")
    await add_file(db_session, storage, lab, "materials/data.xlsx", b"PK", "material")
    await projects_service.create_folder(db_session, lab.id, "empty")

    await build(db_session, storage, fake, lab)

    [request] = fake.requests
    assert request.files() == {
        "main.tex": MAIN_TEX.encode(),
        "meta.tex": "\\newcommand{\\bbtGroup}{БВТ}".encode(),
        "sections/intro.tex": "Введение".encode(),
        # PDF самого проекта — например, картинка для \includegraphics — в сборке.
        "figures/plot.pdf": b"%PDF figure",
        "materials/scheme.png": PNG,
        "materials/PHOTO.JPG": b"jpeg",
        "materials/lab.py": b"print(1)",
    }
    assert request.fields == {"main": "main.tex", "engine": "xelatex", "timeout_s": "60"}


async def test_engine_and_main_file_come_from_project(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await add_file(db_session, storage, lab, "report/lab.tex", MAIN_TEX)
    lab.main_file, lab.engine = "report/lab.tex", "pdflatex"
    await db_session.commit()

    result = await build(db_session, storage, fake, lab)

    assert fake.requests[0].fields["main"] == "report/lab.tex"
    assert fake.requests[0].fields["engine"] == "pdflatex"
    assert result.engine == "pdflatex"


async def test_db_connection_is_released_while_compiling(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    in_transaction: list[bool] = []

    def respond(request: httpx.Request) -> httpx.Response:
        in_transaction.append(db_session.in_transaction())
        return fake.build_response()

    fake.respond = respond

    await build(db_session, storage, fake, lab)

    # Сборка с очередью идёт минутами — соединение из пула всё это время свободно.
    assert in_transaction == [False]


async def test_unsaved_changes_in_session_are_refused(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    # run_build коммитит сессию — чужие незаписанные изменения ушли бы в базу молча.
    lab.title = "Не сохранено"

    with pytest.raises(RuntimeError, match="коммитит сессию"):
        await build(db_session, storage, fake, lab)

    assert fake.requests == []


async def test_project_deleted_during_build_is_not_found(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        # Пока компилятор работает, проект удаляют в другой вкладке.
        await db_session.execute(delete(Project).where(Project.id == lab.id))
        await db_session.commit()
        return fake.build_response()

    fake.respond = respond

    with pytest.raises(AppError) as error:
        await build(db_session, storage, fake, lab)

    assert (error.value.status, error.value.message) == (404, "Проект не найден")
    assert await builds_count(db_session, lab) == 0


# Что сохраняется.


async def test_successful_build_stores_artifacts(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    result = await build(db_session, storage, fake, lab)

    assert (result.status, result.engine, result.duration_ms) == ("ok", "xelatex", 1500)
    assert result.project_id == lab.id
    assert result.inputs_hash is not None
    assert result.pdf_sha256 and result.log_sha256 and result.synctex_sha256
    assert await storage.get(result.pdf_sha256) == PDF
    assert await storage.get(result.log_sha256) == LOG
    assert await storage.get(result.synctex_sha256) == SYNCTEX
    assert await builds_count(db_session, lab) == 1
    # «Output written on out/main.xdv (1 page, …)» в логе.
    assert (result.pages, result.errors) == (1, [])


async def test_errors_and_warnings_come_from_log_with_context(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await add_file(db_session, storage, lab, "sections/intro.tex", "Введение\n\\textbff{x}\n")
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 800}
    fake.files = {
        "output.log": b"(./main.tex (./sections/intro.tex\n"
        b"./sections/intro.tex:2: Undefined control sequence.\n"
        b"l.2 \\textbff\n"
        b")\n"
        b"LaTeX Warning: Reference `fig:1' on page 1 undefined on input line 3.\n"
        b"\n"
        b"Output written on out/main.xdv (1 page, 1234 bytes).\n"
    }

    result = await build(db_session, storage, fake, lab)

    assert result.errors == [
        {
            "file": "sections/intro.tex",
            "line": 2,
            "message": "Undefined control sequence: \\textbff",
            "context": "  1 | Введение\n> 2 | \\textbff{x}",
            "severity": "error",
        },
        {
            "file": "main.tex",
            "line": 3,
            "message": "Reference `fig:1' on page 1 undefined",
            "context": "  1 | \\documentclass{article}\n  2 | \\begin{document}\n"
            "> 3 | Привет\n  4 | \\end{document}",
            "severity": "warning",
        },
    ]
    # PDF не получился — и страниц у сборки нет, хоть TeX их и посчитал.
    assert result.pages is None


async def test_latex_error_keeps_log_without_pdf(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 800}
    fake.files = {"output.log": b"! Undefined control sequence."}

    result = await build(db_session, storage, fake, lab)

    assert result.status == "error"
    assert (result.pdf_sha256, result.synctex_sha256) == (None, None)
    assert result.log_sha256 is not None
    assert await storage.get(result.log_sha256) == b"! Undefined control sequence."


async def test_timeout_explains_what_happened(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    fake.result = {"status": "timeout", "exit_code": None, "duration_ms": 60_000}
    fake.files = {"output.log": b"Latexmk: ..."}

    result = await build(db_session, storage, fake, lab)

    assert result.status == "timeout"
    [error] = result.errors
    assert "60 секунд" in str(error["message"])


async def test_service_problem_goes_before_log_errors(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    fake.result = {"status": "timeout", "exit_code": None, "duration_ms": 60_000}
    fake.files = {"output.log": b"./main.tex:3: Undefined control sequence.\n"}

    result = await build(db_session, storage, fake, lab)

    assert ["60 секунд" in str(error["message"]) for error in result.errors] == [True, False]


async def test_pdf_over_limit_is_error_and_not_stored(
    db_session: AsyncSession,
    storage: LocalStorage,
    fake: FakeCompiler,
    lab: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(builds_service, "MAX_PDF_BYTES", len(PDF) - 1)

    result = await build(db_session, storage, fake, lab)

    assert (result.status, result.pdf_sha256) == ("error", None)
    [error] = result.errors
    assert "PDF получился больше" in str(error["message"])
    assert not await storage.exists(hashlib.sha256(PDF).hexdigest())


async def test_ok_without_pdf_is_treated_as_error(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    fake.files = {"output.log": LOG}

    result = await build(db_session, storage, fake, lab)

    assert (result.status, result.pdf_sha256) == ("error", None)


# Кэш.


async def test_rebuild_without_changes_comes_from_cache(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    first = await build(db_session, storage, fake, lab)
    second = await build(db_session, storage, fake, lab)

    assert len(fake.requests) == 1
    # Новая сборка с теми же файлами: «последняя сборка» — та, что нажали последней.
    assert second.id != first.id
    assert second.status == "ok"
    assert (second.pdf_sha256, second.log_sha256, second.synctex_sha256) == (
        first.pdf_sha256,
        first.log_sha256,
        first.synctex_sha256,
    )
    assert second.inputs_hash == first.inputs_hash
    assert second.created_at > first.created_at


async def test_changed_file_is_built_again(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await build(db_session, storage, fake, lab)
    await projects_service.write_text_file(db_session, lab.id, "main.tex", MAIN_TEX + "%\n")

    await build(db_session, storage, fake, lab)

    assert len(fake.requests) == 2


async def test_new_compiler_version_is_built_again(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await build(db_session, storage, fake, lab)
    fake.version = "2025.2+0123456789abcdef"

    await build(db_session, storage, fake, lab)

    assert len(fake.requests) == 2


async def test_failed_build_is_not_reused(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    fake.result = {"status": "error", "exit_code": 1, "duration_ms": 800}
    fake.files = {"output.log": LOG}
    await build(db_session, storage, fake, lab)
    fake.result, fake.files = ok_result(), {"output.pdf": PDF, "output.log": LOG}

    result = await build(db_session, storage, fake, lab)

    assert len(fake.requests) == 2
    assert result.status == "ok"


@pytest.mark.parametrize("artifact", ["pdf_sha256", "log_sha256", "synctex_sha256"])
async def test_cache_is_skipped_when_any_artifact_is_gone_from_storage(
    db_session: AsyncSession,
    storage: LocalStorage,
    fake: FakeCompiler,
    lab: Project,
    artifact: str,
) -> None:
    first = await build(db_session, storage, fake, lab)
    sha256 = getattr(first, artifact)
    assert sha256 is not None
    await storage.delete(sha256)

    second = await build(db_session, storage, fake, lab)

    assert len(fake.requests) == 2
    assert await storage.exists(getattr(second, artifact))


async def test_cache_is_per_project(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await build(db_session, storage, fake, lab)
    data = ProjectCreate(title="ЛР 2", template_slug="test-lab", fields={})
    other = await projects_service.create_project(db_session, lab.owner_id, data)
    await projects_service.write_text_file(db_session, other.id, "main.tex", MAIN_TEX)

    await build(db_session, storage, fake, other)

    assert len(fake.requests) == 2


def test_inputs_hash_ignores_order_and_follows_every_part() -> None:
    a, b = BuildInput("a.tex", "1" * 64, b""), BuildInput("b.tex", "2" * 64, b"")
    base = inputs_hash([a, b], engine="xelatex", main="main.tex", version=VERSION)

    assert inputs_hash([b, a], engine="xelatex", main="main.tex", version=VERSION) == base
    changed = [
        inputs_hash([a], engine="xelatex", main="main.tex", version=VERSION),
        inputs_hash(
            [a, BuildInput("c.tex", "2" * 64, b"")],
            engine="xelatex",
            main="main.tex",
            version=VERSION,
        ),
        inputs_hash(
            [a, BuildInput("b.tex", "3" * 64, b"")],
            engine="xelatex",
            main="main.tex",
            version=VERSION,
        ),
        inputs_hash([a, b], engine="pdflatex", main="main.tex", version=VERSION),
        inputs_hash([a, b], engine="xelatex", main="a.tex", version=VERSION),
        inputs_hash([a, b], engine="xelatex", main="main.tex", version="2025.2+0"),
    ]
    assert base not in changed
    assert len(set(changed)) == len(changed)


def test_pack_project_has_regular_files_with_utf8_paths() -> None:
    archive = pack_project([("разделы/введение.tex", "Текст".encode()), ("main.tex", b"x")])

    assert CompileRequest({}, archive).files() == {
        "разделы/введение.tex": "Текст".encode(),
        "main.tex": b"x",
    }


# Проблемы проекта: понятная ошибка сборки, компилятор не вызывается.


async def assert_problem_build(
    session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, project: Project, text: str
) -> None:
    result = await build(session, storage, fake, project)

    assert fake.requests == []
    assert result.status == "error"
    assert (result.inputs_hash, result.pdf_sha256, result.log_sha256) == (None, None, None)
    [error] = result.errors
    assert text in str(error["message"])
    assert (error["file"], error["line"], error["severity"]) == (None, None, "error")


async def test_missing_main_file(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await projects_service.delete_path(db_session, lab.id, "main.tex")

    await assert_problem_build(db_session, storage, fake, lab, "нет главного файла main.tex")


async def test_main_file_that_is_a_folder(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await projects_service.create_folder(db_session, lab.id, "report.tex")
    lab.main_file = "report.tex"
    await db_session.commit()

    await assert_problem_build(db_session, storage, fake, lab, "нет главного файла report.tex")


@pytest.mark.parametrize("main", ["отчёт $(id).tex", "-e.tex", "main.txt", "отчёт's.tex"])
async def test_main_file_name_compiler_cannot_take(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project, main: str
) -> None:
    await add_file(db_session, storage, lab, main, MAIN_TEX)
    lab.main_file = main
    await db_session.commit()

    await assert_problem_build(db_session, storage, fake, lab, "недопустимые символы")


async def test_cyrillic_main_file_name_is_fine(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await add_file(db_session, storage, lab, "Отчёт по лабе_2-final.tex", MAIN_TEX)
    lab.main_file = "Отчёт по лабе_2-final.tex"
    await db_session.commit()

    result = await build(db_session, storage, fake, lab)

    assert result.status == "ok"


@pytest.mark.parametrize("path", ["out/old.pdf", "out"])
async def test_out_folder_or_file_in_root(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project, path: str
) -> None:
    await add_file(db_session, storage, lab, path, "старый результат")

    await assert_problem_build(db_session, storage, fake, lab, "Папка out/ в корне проекта занята")


async def test_out_folder_deeper_is_fine(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await add_file(db_session, storage, lab, "sections/out/part.tex", "Часть")

    result = await build(db_session, storage, fake, lab)

    assert result.status == "ok"


async def test_too_many_files(
    db_session: AsyncSession,
    storage: LocalStorage,
    fake: FakeCompiler,
    lab: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(builds_service, "MAX_INPUT_FILES", 1)
    await add_file(db_session, storage, lab, "intro.tex", "Введение")

    await assert_problem_build(db_session, storage, fake, lab, "слишком большой для сборки")


async def test_too_large_project(
    db_session: AsyncSession,
    storage: LocalStorage,
    fake: FakeCompiler,
    lab: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(builds_service, "MAX_INPUT_BYTES", len(MAIN_TEX.encode()))
    await add_file(db_session, storage, lab, "materials/big.png", PNG, "material")

    await assert_problem_build(db_session, storage, fake, lab, "слишком большой для сборки")


# Компилятор недоступен: ошибка запроса, сборка не сохраняется.


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("connect", "Сервис сборки сейчас недоступен"),
        ("server-error", "Сервис сборки сейчас недоступен"),
        ("rejected", "Внутренняя ошибка сервера"),
        ("broken", "Внутренняя ошибка сервера"),
    ],
)
async def test_compiler_failure_is_internal_error_without_build(
    db_session: AsyncSession,
    storage: LocalStorage,
    fake: FakeCompiler,
    lab: Project,
    setup: str,
    message: str,
) -> None:
    responses = {
        "server-error": httpx.Response(500),
        "rejected": httpx.Response(422, json={"error": {"code": "validation_error"}}),
        "broken": httpx.Response(200, content=b"not a tar.gz"),
    }
    if setup == "connect":
        fake.error = httpx.ConnectError("refused")
    else:
        fake.respond = lambda request: responses[setup]

    with pytest.raises(AppError) as error:
        await build(db_session, storage, fake, lab)

    assert (error.value.status, error.value.code) == (500, "internal")
    assert error.value.message.startswith(message)
    assert await builds_count(db_session, lab) == 0
