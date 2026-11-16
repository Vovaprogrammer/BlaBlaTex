"""Команда check-template: собирает шаблон так же, как сервис собирает проект.

Для CI шаблонов (T1.4): `docker compose run --rm compiler check-template templates/<slug>`,
можно сразу несколько папок. Берёт копию папки шаблона, кладёт meta.sample.tex как meta.tex
и собирает главный файл тем движком, что в template.yaml (`main` и `engine`; без
template.yaml — main.tex и XeLaTeX). Печатает ошибки из лога с путём от корня репозитория.
С ключом --github ошибки ещё и становятся пометками GitHub Actions на строках файлов.
Код выхода: 0 — все шаблоны собрались, 1 — нет.

template.yaml целиком проверяет бэкенд (docs/templates.md, «Проверка шаблона»): здесь из него
читаются только main и engine.
"""

import argparse
import asyncio
import io
import re
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import get_args

import yaml

from app.archive import ArchiveError, extract_project
from app.runner import OUT_DIR, Engine, is_valid_main, run_latexmk
from app.version import SHARED_TEX_DIR

MANIFEST = "template.yaml"
SAMPLE_META = "meta.sample.tex"
META = "meta.tex"
# Без template.yaml (тестовый документ класса, эталоны) — как у mtuci-lab.
DEFAULT_MAIN = "main.tex"
DEFAULT_ENGINE: Engine = "xelatex"
ENGINES: tuple[Engine, ...] = get_args(Engine)
# Общий класс в образе лежит в SHARED_TEX_DIR, а в репозитории — здесь (Dockerfile, compose).
SHARED_REPO_DIR = "templates/_shared"
TIMEOUT_S = 120
# Ошибка в формате -file-line-error («./main.tex:12: …», в имени бывают пробелы).
_FILE_ERROR = re.compile(r"^(.+?\.\w+):(\d+): (.*)$")
# Строка исходника, на которой TeX остановился: «l.12 \bbtNoSuchMacro».
_SOURCE_LINE = re.compile(r"^l\.\d+ ")
# Ошибок в логе не нашлось (например, таймаут) — показываем хвост лога.
_TAIL_LINES = 20


@dataclass(frozen=True)
class Target:
    """Что собирать: главный файл и движок."""

    main: str
    engine: Engine


@dataclass(frozen=True)
class TexError:
    """Ошибка из лога TeX: текст, файл и строка, если TeX их назвал, и строка исходника."""

    message: str
    file: str | None = None
    line: int | None = None
    source: str | None = None

    def lines(self) -> list[str]:
        head = f"{self.file}:{self.line}: {self.message}" if self.file else self.message
        return [head] if self.source is None else [head, self.source]


class TemplateProblem(Exception):
    """Шаблон нельзя собрать: текст — что не так."""


def find_errors(log: str) -> list[TexError]:
    """Ошибки из лога TeX: «файл:строка: …» и «! …», к каждой — первая после неё строка l.N.

    Строка l.N показывает, на чём TeX остановился: по ней видно, например, какой макрос
    не определён.
    """
    errors: list[TexError] = []
    for line in log.splitlines():
        match = _FILE_ERROR.match(line)
        if match:
            errors.append(TexError(match[3], match[1], int(match[2])))
        elif line.startswith("! "):
            errors.append(TexError(line))
        elif _SOURCE_LINE.match(line) and errors and errors[-1].source is None:
            errors[-1] = replace(errors[-1], source=line.rstrip())
    return errors


def repo_path(template: PurePosixPath, file: str) -> str | None:
    """Путь файла из лога сборки — в репозитории; файл TeX Live — None.

    Сборка идёт в копии папки шаблона, поэтому «./sections/goal.tex» — это файл шаблона,
    meta.tex — копия meta.sample.tex, а класс лежит в SHARED_TEX_DIR.
    """
    shared = SHARED_TEX_DIR.as_posix() + "/"
    if file.startswith(shared):
        return f"{SHARED_REPO_DIR}/{file.removeprefix(shared)}"
    if file.startswith("/"):
        return None
    name = file.removeprefix("./")
    return (template / (SAMPLE_META if name == META else name)).as_posix()


def github_annotations(template: str, errors: list[TexError], fallback: list[str]) -> list[str]:
    """Пометки GitHub Actions (::error): на строке файла, если она известна.

    Если ни одна ошибка не указывает на файл шаблона или класса, — одна общая пометка
    с fallback: строками ошибок или хвостом лога.
    """
    title = f"{template} не собирается"
    located = [error for error in errors if error.file and not error.file.startswith("/")]
    if not located:
        return [_annotation(title, "\n".join(fallback))]
    return [
        _annotation(
            title,
            "\n".join([error.message, *filter(None, [error.source])]),
            file=error.file,
            line=error.line,
        )
        for error in located
    ]


def read_target(template: Path) -> Target:
    """main и engine из template.yaml шаблона: проект студента собирается ими же."""
    path = template / MANIFEST
    if not path.is_file():
        return Target(DEFAULT_MAIN, DEFAULT_ENGINE)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        first_line = str(error).splitlines()[0] if str(error) else type(error).__name__
        raise TemplateProblem(f"{path}: файл не читается ({first_line})") from error
    if not isinstance(data, dict):
        raise TemplateProblem(f"{path}: нужен словарь ключей, как в docs/templates.md")
    main, engine = data.get("main"), data.get("engine")
    if engine not in ENGINES:
        raise TemplateProblem(f"{path}: engine: {engine} — собираются только xelatex и pdflatex")
    if not isinstance(main, str) or not is_valid_main(main):
        raise TemplateProblem(
            f"{path}: main: {main} — нужен относительный путь к .tex-файлу; "
            "в имени только буквы, цифры, пробел и _ - . /"
        )
    return Target(main, engine)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check-template", description="Собрать шаблоны с meta.sample.tex и показать ошибки."
    )
    parser.add_argument(
        "templates", type=Path, nargs="+", help="папки шаблонов, например templates/mtuci-lab"
    )
    parser.add_argument(
        "--github", action="store_true", help="ошибки ещё и пометками GitHub Actions"
    )
    args = parser.parse_args(argv)
    templates: list[Path] = args.templates

    failed = [template for template in templates if not _check(template, args.github)]
    if len(templates) > 1:
        summary = f"Собрано {len(templates) - len(failed)} из {len(templates)}."
        if failed:
            summary += " С ошибками: " + ", ".join(str(template) for template in failed)
        _say(summary)
    return 1 if failed else 0


def _check(template: Path, github: bool) -> bool:
    """Собирает один шаблон и печатает итог; True — собрался."""
    try:
        target = _prepare(template)
        built, run_info, log = _build(template, target)
    except (TemplateProblem, ArchiveError) as problem:
        text = str(problem) if isinstance(problem, TemplateProblem) else f"{template}: {problem}"
        _say(f"ОШИБКА: {text}")
        if github:
            _say(_annotation(f"{template} не собирается", text))
        return False
    if built:
        _say(f"OK: {template} собран за {run_info} ({target.main}, {target.engine})")
        return True

    root = PurePosixPath(template.as_posix())
    errors = [
        replace(error, file=repo_path(root, error.file) or error.file) if error.file else error
        for error in find_errors(log)
    ]
    shown = [line for error in errors for line in error.lines()]
    if not shown:
        shown = log.splitlines()[-_TAIL_LINES:]
    _say(f"ОШИБКА: {template} не собрался ({run_info})")
    _say("\n".join(shown))
    if github:
        _say("\n".join(github_annotations(str(template), errors, shown)))
    return False


def _prepare(template: Path) -> Target:
    """Что собирать в папке шаблона; папка не годится — TemplateProblem."""
    if not template.is_dir():
        raise TemplateProblem(f"нет папки шаблона {template}")
    target = read_target(template)
    for name in (target.main, SAMPLE_META):
        if not (template / name).is_file():
            raise TemplateProblem(f"в {template} нет файла {name}")
    # Как и в сервисе: старые файлы из out/ выдавались бы за результат сборки.
    if (template / OUT_DIR).exists():
        raise TemplateProblem(f"в {template} есть папка {OUT_DIR}/ — она занята под результаты")
    return target


def _build(template: Path, target: Target) -> tuple[bool, str, str]:
    """Сборка копии шаблона: собрался ли, как прошла (время или статус) и лог TeX."""
    with tempfile.TemporaryDirectory(prefix="check-") as tmp:
        src, console = Path(tmp) / "src", Path(tmp) / "latexmk.txt"
        _copy_template(template, src)
        shutil.copyfile(src / SAMPLE_META, src / META)
        run = asyncio.run(run_latexmk(src, console, target.engine, target.main, TIMEOUT_S))
        # latexmk кладёт результаты в out/ под именем главного файла без папки.
        stem = PurePosixPath(target.main).stem
        tex_log = src / OUT_DIR / f"{stem}.log"
        log_file = tex_log if tex_log.is_file() else console
        log = log_file.read_text(encoding="utf-8", errors="replace")
        built = run.status == "ok" and (src / OUT_DIR / f"{stem}.pdf").is_file()
    info = f"{run.duration_ms} мс" if built else f"status={run.status}, exit_code={run.exit_code}"
    return built, info, log


def _copy_template(template: Path, dest: Path) -> None:
    """Копирует шаблон через ту же распаковку, что и сервис: ссылки и особые файлы — ошибка."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(template.rglob("*")):
            tar.add(path, arcname=path.relative_to(template).as_posix(), recursive=False)
    buffer.seek(0)
    extract_project(buffer, dest)


def _annotation(title: str, message: str, file: str | None = None, line: int | None = None) -> str:
    """Команда GitHub Actions ::error. Переводы строк и спецсимволы экранируются по правилам
    workflow commands: иначе пометка обрежется на первой строке."""
    properties = [f"title={_escape_property(title)}"]
    if file is not None:
        properties.insert(0, f"file={_escape_property(file)}")
        if line is not None:
            properties.insert(1, f"line={line}")
    return f"::error {','.join(properties)}::{_escape_data(message)}"


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")
