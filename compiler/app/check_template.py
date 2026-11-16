"""Команда check-template: собирает шаблон так же, как сервис собирает проект.

Для CI шаблонов (T1.4): `docker compose run --rm compiler check-template templates/<slug>`.
Берёт копию папки шаблона, кладёт meta.sample.tex как meta.tex и собирает главный файл тем
движком, что в template.yaml (`main` и `engine`; без template.yaml — main.tex и XeLaTeX).
Печатает ошибки из лога. Код выхода: 0 — шаблон собрался, 1 — нет.

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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import get_args

import yaml

from app.archive import ArchiveError, extract_project
from app.runner import OUT_DIR, Engine, is_valid_main, run_latexmk

MANIFEST = "template.yaml"
SAMPLE_META = "meta.sample.tex"
# Без template.yaml (тестовый документ класса, эталоны) — как у mtuci-lab.
DEFAULT_MAIN = "main.tex"
DEFAULT_ENGINE: Engine = "xelatex"
ENGINES: tuple[Engine, ...] = get_args(Engine)
TIMEOUT_S = 120
# Ошибка в формате -file-line-error («./main.tex:12: …», в имени бывают пробелы)
# или классическая «! …».
_ERROR_LINE = re.compile(r"^(.+?\.\w+:\d+: |! )")
# Ошибок в логе не нашлось (например, таймаут) — показываем хвост лога.
_TAIL_LINES = 20


@dataclass(frozen=True)
class Target:
    """Что собирать: главный файл и движок."""

    main: str
    engine: Engine


class TemplateProblem(Exception):
    """Шаблон нельзя собрать: текст — что не так."""


def find_errors(log: str) -> list[str]:
    """Строки ошибок из лога TeX."""
    return [line for line in log.splitlines() if _ERROR_LINE.match(line)]


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
        prog="check-template", description="Собрать шаблон с meta.sample.tex и показать ошибки."
    )
    parser.add_argument("template", type=Path, help="папка шаблона, например templates/mtuci-lab")
    template: Path = parser.parse_args(argv).template

    try:
        target = _prepare(template)
    except TemplateProblem as problem:
        _say(f"ОШИБКА: {problem}")
        return 1
    with tempfile.TemporaryDirectory(prefix="check-") as tmp:
        src, console = Path(tmp) / "src", Path(tmp) / "latexmk.txt"
        try:
            _copy_template(template, src)
        except ArchiveError as error:
            _say(f"ОШИБКА: {template}: {error}")
            return 1
        shutil.copyfile(src / SAMPLE_META, src / "meta.tex")
        run = asyncio.run(run_latexmk(src, console, target.engine, target.main, TIMEOUT_S))
        # latexmk кладёт результаты в out/ под именем главного файла без папки.
        stem = PurePosixPath(target.main).stem
        tex_log = src / OUT_DIR / f"{stem}.log"
        log_file = tex_log if tex_log.is_file() else console
        log = log_file.read_text(encoding="utf-8", errors="replace")
        built = run.status == "ok" and (src / OUT_DIR / f"{stem}.pdf").is_file()

    if built:
        _say(f"OK: {template} собран за {run.duration_ms} мс ({target.main}, {target.engine})")
        return 0
    _say(f"ОШИБКА: {template} не собрался (status={run.status}, exit_code={run.exit_code})")
    _say("\n".join(find_errors(log) or log.splitlines()[-_TAIL_LINES:]))
    return 1


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


def _copy_template(template: Path, dest: Path) -> None:
    """Копирует шаблон через ту же распаковку, что и сервис: ссылки и особые файлы — ошибка."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(template.rglob("*")):
            tar.add(path, arcname=path.relative_to(template).as_posix(), recursive=False)
    buffer.seek(0)
    extract_project(buffer, dest)


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")
