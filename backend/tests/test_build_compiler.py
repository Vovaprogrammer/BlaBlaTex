"""Сборка против настоящего компилятора из docker compose.

По умолчанию не запускается: в CI компилятора нет, а образ собирается минуты.
Локально — после `docker compose up -d`:

    uv run pytest -m compiler
"""

import base64
import functools
import io
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pdfminer.high_level import extract_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TEMPLATES_DIR, Settings
from app.core.storage import LocalStorage
from app.modules.auth import service as auth_service
from app.modules.builds.compiler import (
    CompilerClient,
    CompilerError,
    CompileResult,
    create_http_client,
)
from app.modules.builds.dependencies import get_api_compiler
from app.modules.builds.models import Build
from app.modules.builds.service import pack_project, queue_build, run_queued_build
from app.modules.profiles.models import Profile
from app.modules.projects import service as projects_service
from app.modules.projects.models import File, Project
from app.modules.templates.meta import render_meta
from app.modules.templates.registry import META_FILE, Template, load_templates
from app.modules.templates.service import CLASS_MACROS
from tests.build_worker import BuildWorker
from tests.fake_events import FakeEvents
from tests.helpers import create_empty_project, writer

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
    project = await create_empty_project(db_session, user.id)
    await projects_service.write_text_file(db_session, writer(), project.id, "main.tex", MAIN_TEX)
    await projects_service.write_text_file(
        db_session,
        writer(),
        project.id,
        "sections/intro.tex",
        "Съешь же ещё этих мягких французских булок.",
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


async def build(
    session: AsyncSession, storage: LocalStorage, compiler: CompilerClient, project: Project
) -> Build:
    """Сборка целиком, как у воркера: в очередь и сразу собрать."""
    queued, _ = await queue_build(session, project)
    result = await run_queued_build(session, storage, compiler, FakeEvents(), queued.id)
    assert result is not None
    return result


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

    first = await build(db_session, storage, compiler, lab)
    second = await build(db_session, storage, compiler, lab)

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
        db_session, writer(), lab.id, "sections/intro.tex", "\\undefinedmacro"
    )

    result = await build(db_session, storage, compiler, lab)

    assert (result.status, result.pdf_sha256, result.pages) == ("error", None, None)
    assert result.log_sha256 is not None
    log = await storage.get(result.log_sha256)
    assert b"./sections/intro.tex:1: Undefined control sequence" in log
    # Парсер нашёл ошибку в подключённом файле и показал её место.
    [error] = result.errors
    assert (error["file"], error["line"], error["severity"]) == ("sections/intro.tex", 1, "error")
    assert error["message"] == "Undefined control sequence: \\undefinedmacro"
    assert error["context"] == "> 1 | \\undefinedmacro"


async def test_listing_by_bbtcode_hint_keeps_first_code_line(
    db_session: AsyncSession, storage: LocalStorage, compiler: CompilerClient, lab: Project
) -> None:
    # Документ ровно по подсказке агенту, только с настоящими аргументами и кодом.
    [usage] = [macro.usage for macro in CLASS_MACROS if macro.usage.startswith("\\begin{bbtcode}")]
    listing = usage.replace("{language}{caption}{label}", "{Python}{Сортировка}{lst:sort}")
    listing = listing.replace("\ncode\n", "\nprint(111)\nprint(222)\n")
    main = "\\documentclass{mtuci-report}\n\\begin{document}\n" + listing + "\n\\end{document}\n"
    await projects_service.write_text_file(db_session, writer(), lab.id, "main.tex", main)

    result = await build(db_session, storage, compiler, lab)

    assert result.status == "ok", result.errors
    assert result.pdf_sha256 is not None
    text = extract_text(io.BytesIO(await storage.get(result.pdf_sha256)))
    assert "print(111)" in text
    assert "print(222)" in text


async def test_api_serves_pdf_built_by_real_compiler(
    user_client: AsyncClient,
    build_worker: BuildWorker,
    project: dict[str, Any],  # Any — проект как JSON из ответа API
    compiler: CompilerClient,
) -> None:
    build_worker.compiler = compiler
    pid = project["id"]
    doc = "\\documentclass{article}\n\\begin{document}\nПривет, PDF.\n\\end{document}\n"
    written = await user_client.put(f"/api/v1/projects/{pid}/files/main.tex", content=doc)
    # main.tex уже есть — он из шаблона test-lab, запись его заменяет.
    assert written.status_code == 200

    started = await user_client.post(f"/api/v1/projects/{pid}/builds")
    await build_worker.run()
    build = (await user_client.get(f"/api/v1/builds/{started.json()['id']}")).json()
    pdf = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")

    assert started.status_code == 202
    assert (build["status"], build["has_pdf"], build["pages"]) == ("ok", True, 1)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


SYNCTEX_MAIN_TEX = r"""\documentclass{article}
\usepackage{fontspec}
\setmainfont{Liberation Serif}
\usepackage[russian]{babel}
\begin{document}
\input{sections/intro}
\end{document}
"""
SYNCTEX_INTRO_TEX = """Первый абзац раздела.

Второй абзац раздела, отдельной строкой.
"""


async def test_api_synctex_with_real_compiler(
    app: FastAPI,
    user_client: AsyncClient,
    build_worker: BuildWorker,
    project: dict[str, Any],  # Any — проект как JSON из ответа API
    compiler: CompilerClient,
) -> None:
    build_worker.compiler = compiler
    app.dependency_overrides[get_api_compiler] = lambda: compiler
    pid = project["id"]
    await user_client.put(f"/api/v1/projects/{pid}/files/main.tex", content=SYNCTEX_MAIN_TEX)
    await user_client.put(
        f"/api/v1/projects/{pid}/files/sections/intro.tex", content=SYNCTEX_INTRO_TEX
    )
    started = await user_client.post(f"/api/v1/projects/{pid}/builds")
    await build_worker.run()
    url = f"/api/v1/builds/{started.json()['id']}/synctex"

    view = await user_client.get(f"{url}/view", params={"path": "sections/intro.tex", "line": 3})
    [box, *_] = view.json()["boxes"]
    middle = {"page": box["page"], "x": box["x"] + 20, "y": box["y"] + box["height"] / 2}
    edit = await user_client.get(f"{url}/edit", params=middle)
    # Низ страницы: только номер, а страница ушла в печать на строке \end{document}.
    bottom = await user_client.get(f"{url}/edit", params={"page": 1, "x": 306, "y": 760})
    meta = await user_client.get(f"{url}/view", params={"path": "meta.tex", "line": 1})

    assert box["page"] == 1
    assert edit.json() == {"source": {"path": "sections/intro.tex", "line": 3}}
    assert bottom.json() == {"source": None}
    assert meta.json() == {"boxes": []}


# Все макросы meta.tex (9.6) из профиля и полей шаблона test-lab подряд.
META_MAIN_TEX = r"""\documentclass{article}
\usepackage{fontspec}
\setmainfont{Liberation Serif}
\usepackage[russian]{babel}
\input{meta}
\begin{document}
\bbtLastName, \bbtFirstName, \bbtMiddleName. \bbtShortName. \bbtFullName.
\bbtGroup, \bbtFaculty, \bbtDepartment. \bbtDiscipline. \bbtCity, \bbtYear.
\bbtLabNumber. \bbtLabTitle. \bbtVariant.
\end{document}
"""
HARD = "Ёлкин-Палкин & Co_1 #2 {x} ~ ^ \\ %"


async def test_meta_with_tex_special_characters_builds(
    user_client: AsyncClient,
    build_worker: BuildWorker,
    project: dict[str, Any],  # Any — проект как JSON из ответа API
    compiler: CompilerClient,
) -> None:
    build_worker.compiler = compiler
    pid = project["id"]
    profile = {
        "last_name": HARD,
        "first_name": "_Пётр",
        "middle_name": "{С}",
        "group_name": "БВТ#1",
        "faculty": "50% $",
        "department": "\\textbf{x}",
    }
    fields = {"lab_number": 1, "lab_title": HARD, "variant": "Строка 1\n\nСтрока 2"}
    assert (await user_client.put("/api/v1/profile", json=profile)).status_code == 200
    patched = await user_client.patch(f"/api/v1/projects/{pid}", json={"fields": fields})
    assert patched.status_code == 200
    await user_client.put(f"/api/v1/projects/{pid}/files/main.tex", content=META_MAIN_TEX)

    started = await user_client.post(f"/api/v1/projects/{pid}/builds")
    await build_worker.run()
    build = (await user_client.get(f"/api/v1/builds/{started.json()['id']}")).json()

    assert (build["status"], build["errors"], build["has_pdf"]) == ("ok", [], True)


# Титульник: трудные случаи (T2.1). Профиль и поля проекта по умолчанию — обычный титул;
# каждый случай меняет в них то, что проверяет. meta.tex создаёт render_meta, как в проекте.
TITLE_PROFILE = {
    "last_name": "Смирнов",
    "first_name": "Илья",
    "middle_name": "Андреевич",
    "group_name": "БВТ2401",
    "faculty": "Информационные технологии",
    "department": "Математическая кибернетика и информационные технологии",
}
TITLE_FIELDS: dict[str, str | int] = {
    "discipline": "Структуры и алгоритмы обработки данных",
    "lab_number": 2,
    "lab_title": "Методы поиска в массиве",
    "variant": "12",
    "teacher": "доц. Петров П. П.",
    "work_type": "Лабораторная работа",
}
# 196 символов — почти предел строкового поля (200).
LONG_TOPIC = (
    "Разработка и сравнительный анализ эффективности алгоритмов сортировки слиянием, "
    "быстрой сортировки и пирамидальной сортировки на массивах большого размера "
    "с замерами времени работы и объёма памяти"
)


LONG_NAME = {
    "last_name": "Константинопольская-Преображенская",
    "first_name": "Александра",
    "middle_name": "Вячеславовна",
}
LONG_TEACHER = "ст. преп. кафедры МКиИТ, к.т.н. Ахмедова-Здравомыслова Е. В."


def _max_length(words: str) -> str:
    """Слова, повторённые до 200 символов — предела полей профиля и строковых полей."""
    return (words * 20)[:200].strip()


@dataclass(frozen=True)
class TitleCase:
    profile: dict[str, str] = field(default_factory=dict)
    fields: dict[str, str | int] = field(default_factory=dict)
    # Строки первой страницы; пробелы и переводы строк — один пробел.
    expected: tuple[str, ...] = ()
    # Чего на первой странице быть не должно.
    absent: tuple[str, ...] = ()


TITLE_CASES = {
    # Длинная двойная фамилия и преподаватель с должностью и степенью: вместе не помещаются
    # в строку блока подписей.
    "long-name": TitleCase(
        profile=LONG_NAME,
        fields={"teacher": LONG_TEACHER},
        expected=("Константинопольская-Преображенская А. В.", "Ахмедова-Здравомыслова Е. В."),
    ),
    # Самый высокий титул из жизни: кафедра, дисциплина и тема — каждая на пределе поля,
    # длинные ФИО и преподаватель. ФИО и группа по 200 символов не бывают, их не проверяем.
    "max-lengths": TitleCase(
        profile=LONG_NAME
        | {"department": _max_length("Математическая кибернетика и информационные технологии ")},
        fields={
            "discipline": _max_length("Структуры и алгоритмы обработки данных "),
            "lab_title": _max_length("Очень длинная тема работы "),
            "teacher": LONG_TEACHER,
        },
    ),
    "yo": TitleCase(
        profile={"last_name": "Ёлкина", "first_name": "Алёна", "middle_name": "Фёдоровна"},
        # Кавычки внутри темы — часть темы, класс их не трогает.
        fields={"lab_title": "«Ёмкость» и «объём» хеш-таблиц", "teacher": "проф. Королёв Ё. Ё."},
        expected=("Ёлкина А. Ф.", "на тему ««Ёмкость» и «объём» хеш-таблиц»", "Королёв Ё. Ё."),
    ),
    "double-surname": TitleCase(
        profile={"last_name": "Петрова-Водкина", "first_name": "Анна", "middle_name": "Сергеевна"},
        expected=("Петрова-Водкина А. С.",),
    ),
    "no-middle-name": TitleCase(
        profile={"last_name": "Ли", "first_name": "Виктория", "middle_name": ""},
        expected=("Ли В.",),
    ),
    "special-chars": TitleCase(
        fields={
            "lab_title": 'Хеш-таблицы & деревья: 100% покрытие hash_map_put, #1 $5 {x} ~ ^ \\ "к"'
        },
        expected=("Хеш-таблицы & деревья: 100% покрытие hash_map_put, #1 $5 {x}",),
    ),
    "long-topic": TitleCase(
        fields={"lab_title": LONG_TOPIC},
        expected=("на тему «Разработка и сравнительный анализ",),
    ),
    # Студент ввёл как в методичке: со словом «Кафедра», в кавычках, с точкой.
    "quoted": TitleCase(
        profile={"department": "Кафедра «МКиИТ»"},
        fields={
            "discipline": "«Структуры и алгоритмы обработки данных».",
            "lab_title": '"Методы поиска в массиве."',
        },
        expected=(
            "Кафедра «МКиИТ»",
            "по дисциплине «Структуры и алгоритмы обработки данных» на тему",
            "на тему «Методы поиска в массиве» Вариант",
        ),
        # Прямые кавычки шрифт печатает как ”.
        absent=("««", "»»", "”"),
    ),
    # «Кафедра» внутри кавычек и заглавными, с двоеточием.
    "department-word": TitleCase(
        profile={"department": "«КАФЕДРА: МКиИТ»."},
        expected=("Кафедра «МКиИТ»",),
        absent=("КАФЕДРА", "««"),
    ),
    # Кавычки внутри значения и многоточие — часть текста: остаются.
    "kept-quotes": TitleCase(
        fields={
            "discipline": "Алгоритмы и структуры данных...",
            "lab_title": "«Быстрая» сортировка против «пирамидальной»",
        },
        expected=(
            "по дисциплине «Алгоритмы и структуры данных...»",
            "на тему ««Быстрая» сортировка против «пирамидальной»»",
        ),
    ),
}


@functools.cache
def _lab_template() -> Template:
    return load_templates(TEMPLATES_DIR)["mtuci-lab"]


def _page_text(pdf: bytes, page: int) -> str:
    return " ".join(extract_text(io.BytesIO(pdf), page_numbers=[page]).split())


@pytest.mark.parametrize("case", TITLE_CASES.values(), ids=TITLE_CASES.keys())
async def test_title_page_edge_case(compiler: CompilerClient, case: TitleCase) -> None:
    """Собирается без ошибок, не вылезает за поле и помещается на один лист."""
    template = _lab_template()
    profile = Profile(user_id=uuid.uuid4(), **(TITLE_PROFILE | case.profile))
    meta = render_meta(profile, template.manifest, TITLE_FIELDS | case.fields)
    files = {**template.files, META_FILE: meta}
    archive = pack_project([(path, text.encode()) for path, text in files.items()])

    result = await compiler.compile(archive, main=template.manifest.main, engine="xelatex")

    assert result.status == "ok", result.log.decode(errors="replace")[-3000:]
    assert result.pdf is not None
    assert b"Overfull \\hbox" not in result.log
    title, next_page = _page_text(result.pdf, 0), _page_text(result.pdf, 1)
    assert title.startswith("Министерство цифрового развития")
    assert "Москва" in title
    assert "Преподаватель" not in next_page
    for text in case.expected:
        assert text in title
    for text in case.absent:
        assert text not in title
