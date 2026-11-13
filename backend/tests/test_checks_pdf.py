"""Проверки по PDF на примерах из docs/checks.md: build-failed, text-overflow, missing-glyph.

Логи — настоящие, от компилятора из docker compose (tests/checks_pdf_samples.py). Тест
с пометкой compiler собирает те же примеры заново: uv run pytest -m compiler.
"""

from collections.abc import AsyncIterator, Mapping

import pytest

from app.core.config import Settings
from app.modules.builds.compiler import CompilerClient, CompilerError, create_http_client
from app.modules.builds.log_parser import parse_log
from app.modules.builds.service import pack_project
from app.modules.checks.context import BuildOutcome
from app.modules.checks.engine import check_project
from app.modules.checks.schemas import CheckFinding, CheckId
from tests.checks_pdf_samples import CONCLUSION, GLYPH, OVERFLOW, PROGRESS, UNCLOSED
from tests.checks_samples import FIXTURES, lab_files, places, run, snapshot


def log(name: str) -> bytes:
    return (FIXTURES / f"{name}.log").read_bytes()


def pdf_run(check: CheckId, changes: Mapping[str, str], build: BuildOutcome) -> list[CheckFinding]:
    return run(check, changes, build=build)


def test_build_failed_example() -> None:
    parsed = parse_log(log("unclosed"), lab_files(), "xelatex")
    errors = sum(error.severity == "error" for error in parsed.errors)
    build = BuildOutcome("error", errors, log("unclosed"))

    [finding] = pdf_run("build-failed", UNCLOSED, build)

    assert (finding.file, finding.line, finding.place, finding.level) == (
        None,
        None,
        "build",
        "error",
    )
    assert finding.message == (
        f"PDF не собрался: в сборке ошибок — {errors}. Откройте ошибки сборки или попросите ИИ "
        "их исправить."
    )


def test_build_failed_timeout() -> None:
    [finding] = run("build-failed", build=BuildOutcome("timeout", 1, None))

    assert finding.message == (
        "Сборка не уложилась во время, PDF не обновился. Чаще всего мешают очень большие "
        "картинки: сожмите их или сохраните в JPEG."
    )


def test_build_failed_does_not_fire_on_ok_build_with_warnings() -> None:
    # В логе предупреждения «Reference … undefined» — их ловит ref-broken, а не build-failed.
    assert run("build-failed", OVERFLOW, build=BuildOutcome("ok", 0, log("overflow"))) == []


def test_pdf_checks_need_build() -> None:
    checks = {"build-failed", "text-overflow", "missing-glyph"}

    assert check_project(snapshot(OVERFLOW), checks, None) == []


def test_text_overflow_example() -> None:
    found = pdf_run("text-overflow", OVERFLOW, BuildOutcome("ok", 0, log("overflow")))

    assert places(found) == [(PROGRESS, 3), (PROGRESS, 5)]
    assert [finding.message for finding in found] == [
        "Текст выходит за правое поле на 121,6 мм. Обычно мешает длинное слово без пробелов — "
        "имя функции, путь или адрес. Попросите ИИ перефразировать или разбить его.",
        "Таблица шире страницы на 131,9 мм. Попросите ИИ сократить заголовки столбцов или "
        "разбить таблицу.",
    ]
    assert {finding.level for finding in found} == {"warning"}


def test_text_overflow_ignores_less_than_a_millimetre() -> None:
    small = log("overflow").replace(b"(345.91956pt too wide)", b"(1.2pt too wide)      ")
    build = BuildOutcome("ok", 0, small)

    assert places(pdf_run("text-overflow", OVERFLOW, build)) == [(PROGRESS, 5)]


def test_text_overflow_in_code_file_points_to_macro() -> None:
    progress = (
        "\\section{Ход работы}\nКод — в листинге~\\ref{lst:main}.\n"
        "\\bbtCodeFile[python]{materials/main.py}{Программа}{lst:main}\n"
    )
    fake_log = (
        b"(./main.tex (./sections/progress.tex (./materials/main.py\n"
        b"Overfull \\hbox (30.0pt too wide) in paragraph at lines 12--12\n"
        b"[]\\TU/LiberationMono(0)/m/n/10 x\n\n))\n)\n"
    )

    found = pdf_run("text-overflow", {PROGRESS: progress}, BuildOutcome("ok", 0, fake_log))

    assert places(found) == [(PROGRESS, 3)]


def test_missing_glyph_example() -> None:
    [finding] = pdf_run("missing-glyph", GLYPH, BuildOutcome("ok", 0, log("glyph")))

    assert (finding.file, finding.line, finding.level) == (CONCLUSION, 4, "warning")
    assert finding.message == (
        "Символа «✅» нет в шрифте отчёта, и в PDF он пропал. Замените его словом или обычным "
        "знаком, например «✅» на «[OK]», или уберите. Если символ в вашем коде или выводе "
        "программы — исправьте материал или оставьте как есть."
    )


def test_missing_glyph_in_code_file_points_to_macro() -> None:
    progress = (
        "\\section{Ход работы}\nКод — в листинге~\\ref{lst:main}.\n"
        "\\bbtCodeFile[python]{code/main.py}{Программа}{lst:main}\n"
    )
    changes = {PROGRESS: progress, "code/main.py": "print('₽')\nprint('₽')\n"}
    fake_log = (
        b"(./main.tex (./sections/progress.tex (./code/main.py\n"
        b"Missing character: There is no \xe2\x82\xbd (U+20BD) in font Liberation Mono/OT:sc"
        b"ript=latn;language=dflt;!\n"
        b"Missing character: There is no \xe2\x82\xbd (U+20BD) in font Liberation Mono/OT:sc"
        b"ript=latn;language=dflt;!\n))\n)\n"
    )

    found = pdf_run("missing-glyph", changes, BuildOutcome("ok", 0, fake_log))

    assert [(f.file, f.line, "«₽»" in f.message) for f in found] == [(PROGRESS, 3, True)]


def test_missing_glyph_does_not_fire_on_cyrillic() -> None:
    # Кириллица, «–», «№» и рамки есть в шрифтах: в логе таких строк нет.
    assert pdf_run("missing-glyph", OVERFLOW, BuildOutcome("ok", 0, log("overflow"))) == []


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


@pytest.mark.compiler
@pytest.mark.parametrize(
    ("changes", "status", "expected"),
    [
        (OVERFLOW, "ok", [("text-overflow", PROGRESS, 3), ("text-overflow", PROGRESS, 5)]),
        (GLYPH, "ok", [("missing-glyph", CONCLUSION, 4)]),
        (UNCLOSED, "error", [("build-failed", None, None)]),
    ],
)
async def test_pdf_checks_on_real_build(
    compiler: CompilerClient,
    changes: Mapping[str, str],
    status: str,
    expected: list[tuple[str, str | None, int | None]],
) -> None:
    files = {**lab_files(), **changes}
    archive = pack_project([(path, text.encode()) for path, text in files.items()])

    result = await compiler.compile(archive, main="main.tex", engine="xelatex")

    errors = len(
        [e for e in parse_log(result.log, files, "xelatex").errors if e.severity == "error"]
    )
    build = BuildOutcome(result.status, errors, result.log)
    checks: set[CheckId] = {"build-failed", "text-overflow", "missing-glyph"}
    found = check_project(snapshot(changes), checks, build)
    assert result.status == status
    assert [(finding.check, finding.file, finding.line) for finding in found] == expected
