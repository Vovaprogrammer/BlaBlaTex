"""Команда check-template: собирает шаблон так же, как сервис собирает проект.

Для CI шаблонов (T1.4): `docker compose run --rm compiler check-template templates/<slug>`.
Берёт копию папки шаблона, кладёт meta.sample.tex как meta.tex, собирает XeLaTeX
и печатает ошибки из лога. Код выхода: 0 — шаблон собрался, 1 — нет.
"""

import argparse
import asyncio
import io
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from app.archive import ArchiveError, extract_project
from app.runner import OUT_DIR, run_latexmk

MAIN = "main.tex"
SAMPLE_META = "meta.sample.tex"
TIMEOUT_S = 120
# Ошибка в формате -file-line-error («./main.tex:12: …», в имени бывают пробелы)
# или классическая «! …».
_ERROR_LINE = re.compile(r"^(.+?\.\w+:\d+: |! )")
# Ошибок в логе не нашлось (например, таймаут) — показываем хвост лога.
_TAIL_LINES = 20


def find_errors(log: str) -> list[str]:
    """Строки ошибок из лога TeX."""
    return [line for line in log.splitlines() if _ERROR_LINE.match(line)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check-template", description="Собрать шаблон с meta.sample.tex и показать ошибки."
    )
    parser.add_argument("template", type=Path, help="папка шаблона, например templates/mtuci-lab")
    template: Path = parser.parse_args(argv).template

    problem = _layout_problem(template)
    if problem:
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
        run = asyncio.run(run_latexmk(src, console, "xelatex", MAIN, TIMEOUT_S))
        tex_log = src / OUT_DIR / "main.log"
        log_file = tex_log if tex_log.is_file() else console
        log = log_file.read_text(encoding="utf-8", errors="replace")
        built = run.status == "ok" and (src / OUT_DIR / "main.pdf").is_file()

    if built:
        _say(f"OK: {template} собран за {run.duration_ms} мс")
        return 0
    _say(f"ОШИБКА: {template} не собрался (status={run.status}, exit_code={run.exit_code})")
    _say("\n".join(find_errors(log) or log.splitlines()[-_TAIL_LINES:]))
    return 1


def _layout_problem(template: Path) -> str | None:
    if not template.is_dir():
        return f"нет папки шаблона {template}"
    for name in (MAIN, SAMPLE_META):
        if not (template / name).is_file():
            return f"в {template} нет файла {name}"
    # Как и в сервисе: старые файлы из out/ выдавались бы за результат сборки.
    if (template / OUT_DIR).exists():
        return f"в {template} есть папка {OUT_DIR}/ — она занята под результаты сборки"
    return None


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
