"""Запросы SyncTeX по файлу сборки (architecture.md 9.7): место в PDF ↔ строка файла проекта.

Компилятор ничего не хранит: файл output.synctex.gz приходит в каждом запросе. Он
распаковывается во временную папку и правится (prepare_synctex), а отвечает программа synctex
из TeX Live — она умеет находить ближайший текст, если точного места нет.
"""

import asyncio
import errno
import gzip
import math
import os
import re
import shutil
import signal
import tempfile
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import IO

from pydantic import BaseModel

from app.archive import MB, is_safe_relative_path
from app.runner import JOB_PREFIX, OUT_DIR, SOURCE_DIR

# Файл SyncTeX — до 64 МБ и в сжатом, и в распакованном виде: столько разрешено любому файлу
# сборки (runner.MAX_OUTPUT_FILE_BYTES), а память и tmpfs запросы SyncTeX делят со сборками.
MAX_SYNCTEX_BYTES = 64 * MB
# Строки файла SyncTeX короткие: в записях — числа, в Input — путь файла.
MAX_LINE_BYTES = 64 * 1024
SYNCTEX_TIMEOUT_S = 10
# Вывод synctex идёт в файл и не больше этого: так он не копится в памяти сервиса.
MAX_STDOUT_BYTES = 4 * MB
# Строка \bbtTitlePage даёт пару десятков прямоугольников, строка кода — несколько.
MAX_BOXES = 100

SYNCTEX_NAME = "output.synctex"
# synctex находит файл SyncTeX по имени PDF, сам PDF ему не нужен.
PDF_NAME = "output.pdf"
STDOUT_NAME = "synctex.txt"

# Файл проекта в сборке — /tmp/job-<случайное>/src/./sections/goal.tex: tempfile в образе
# создаёт папки в /tmp (main.py). Файлы TeX Live, общего класса и out/ проектом не считаются.
_PROJECT_INPUT = re.compile(rf"/tmp/{re.escape(JOB_PREFIX)}[^/]+/{SOURCE_DIR}/(.+)")
_INPUT = re.compile(rb"Input:(\d+):(.*)")
# Запись с местом в исходнике: тип, тег файла, строка — [7,12:… ; (7,12:… ; k7,12:… и т. д.
_RECORD = re.compile(rb"([\[(hvxkg$])(\d+),(\d+):")
# «Файл», куда prepare_synctex переносит записи страницы со строкой, на которой она ушла в
# печать. Путь абсолютный — find_source не примет его за файл проекта. Теги TeX — номера
# файлов по порядку открытия, до этого номера они не дойдут.
PAGE_TAG = b"999999"
PAGE_INPUT = b"Input:" + PAGE_TAG + b":/blablatex/page\n"


class SyncTexFileError(Exception):
    """Файл не gzip или не SyncTeX. Сообщение — для бэкенда, на русском."""


class SyncTexTooLargeError(Exception):
    """Файл SyncTeX больше MAX_SYNCTEX_BYTES в сжатом или распакованном виде."""


class SyncTexRunError(Exception):
    """synctex не ответил за SYNCTEX_TIMEOUT_S, упал или вывел слишком много."""


class Source(BaseModel):
    """Место в файле проекта."""

    path: str
    line: int


class Box(BaseModel):
    """Прямоугольник на странице: пункты PDF от левого верхнего угла, ось y — вниз."""

    page: int
    x: float
    y: float
    width: float
    height: float


def project_path(name: str) -> str | None:
    """Путь проекта для файла, который записан в SyncTeX; None — файл не из проекта."""
    match = _PROJECT_INPUT.fullmatch(name)
    if match is None:
        return None
    # Файлы, найденные через «.» в TEXINPUTS, TeX записывает как src/./sections/goal.tex.
    segments = [segment for segment in match.group(1).split("/") if segment != "."]
    path = "/".join(segments)
    if not is_safe_relative_path(path) or segments[0] == OUT_DIR:
        return None
    return path


def prepare_synctex(source: IO[bytes], workdir: Path) -> None:
    """Распаковывает SyncTeX сборки в workdir/output.synctex для программы synctex.

    По пути файл правится так:
    - пути файлов проекта становятся относительными, как в проекте: synctex отвечает ими, а
      в запросе view сравнивает путь целиком, и goal.tex не совпадёт с sections/goal.tex;
    - записи линеек (r) убираются: SyncTeX пишет их не со своей строкой, а со строкой, на
      которой страница ушла в печать, — клик по заголовку или коду попадал бы туда;
    - записи страницы с этой же строкой — сама страница, номер, весь титульный лист — уходят
      в «файл» PAGE_INPUT. Иначе клик по номеру страницы открывал бы, например, заголовок
      следующего раздела, а курсор на \\documentclass подсвечивал бы титульный лист.
      Строки текста при этом находятся: у слов и пробелов в них свои записи со своей строкой.
    """
    page_starts = False
    shipped: tuple[bytes, bytes] | None = None
    unpacked = 0
    try:
        with (
            gzip.GzipFile(fileobj=source, mode="rb") as packed,
            (workdir / SYNCTEX_NAME).open("wb") as out,
        ):
            line = packed.readline(MAX_LINE_BYTES)
            if not line.startswith(b"SyncTeX Version:"):
                raise SyncTexFileError("Это не файл SyncTeX")
            unpacked = len(line)
            out.write(line + PAGE_INPUT)
            while line := packed.readline(MAX_LINE_BYTES):
                unpacked += len(line)
                if unpacked > MAX_SYNCTEX_BYTES:
                    raise SyncTexTooLargeError(
                        f"Файл SyncTeX в распакованном виде больше {MAX_SYNCTEX_BYTES // MB} МБ"
                    )
                if len(line) == MAX_LINE_BYTES and not line.endswith(b"\n"):
                    raise SyncTexFileError("Файл SyncTeX повреждён: слишком длинная строка")
                if line.startswith(b"r"):
                    continue
                if line.startswith(b"Input:"):
                    line = _rewrite_input(line)
                elif line.startswith((b"{", b"}")):
                    page_starts, shipped = line.startswith(b"{"), None
                elif match := _RECORD.match(line):
                    location = match.group(2), match.group(3)
                    if page_starts:
                        # Первая запись страницы — сама страница: её строка — где её отправили
                        # в печать.
                        page_starts, shipped = False, location
                    if location == shipped:
                        line = match.group(1) + PAGE_TAG + line[match.end(2) :]
                out.write(line)
    except (OSError, EOFError, zlib.error) as error:
        # Кончилось место в tmpfs — файл тут ни при чём, пусть будет внутренняя ошибка.
        if isinstance(error, OSError) and error.errno == errno.ENOSPC:
            raise
        raise SyncTexFileError("Файл SyncTeX повреждён или это не gzip") from error


def _rewrite_input(line: bytes) -> bytes:
    """Input:тег:путь — путь файла проекта заменяется путём в проекте."""
    match = _INPUT.fullmatch(line.rstrip(b"\n"))
    if match is None:
        return line
    tag, raw = match.groups()
    path = project_path(raw.decode(errors="replace"))
    if path is None:
        return line
    return b"Input:" + tag + b":" + path.encode() + b"\n"


def parse_output(text: str) -> list[dict[str, str]]:
    """Записи ответа synctex между «SyncTeX result begin» и «end»; каждая — с Output:."""
    records: list[dict[str, str]] = []
    inside = False
    for line in text.splitlines():
        if line == "SyncTeX result begin":
            inside = True
        elif line == "SyncTeX result end":
            break
        elif inside and ":" in line:
            key, value = line.split(":", 1)
            if key == "Output":
                records.append({})
            elif records:
                records[-1].setdefault(key, value)
    return records


def find_source(records: list[dict[str, str]]) -> Source | None:
    """Ответ synctex edit → место в проекте; None — здесь нет текста студента.

    Берётся первая запись — synctex ставит самую точную первой.
    """
    if not records:
        return None
    name = records[0].get("Input", "")
    try:
        line = int(records[0].get("Line", ""))
    except ValueError:
        return None
    # Файлы проекта prepare_synctex сделал относительными. Абсолютный путь — TeX Live,
    # общий класс, out/ или PAGE_INPUT: номер страницы, поля, титульный лист.
    if line < 1 or not is_safe_relative_path(name):
        return None
    return Source(path=name, line=line)


def find_boxes(records: list[dict[str, str]]) -> list[Box]:
    """Ответ synctex view → прямоугольники без повторов, в порядке synctex: первый — точнее."""
    boxes: list[Box] = []
    seen: set[tuple[int, float, float, float, float]] = set()
    for record in records:
        try:
            page = int(record["Page"])
            h, v, width, height = (float(record[key]) for key in ("h", "v", "W", "H"))
        except (KeyError, ValueError):
            continue
        if not all(map(math.isfinite, (h, v, width, height))):
            continue
        # У synctex (h, v) — левый край и базовая линия, высота отсчитывается вверх. Строка
        # листинга начинается левее страницы — обрезаем по её краю.
        left, top = max(h, 0.0), max(v - height, 0.0)
        right, bottom = h + width, v
        key = (
            page,
            round(left, 2),
            round(top, 2),
            round(right - left, 2),
            round(bottom - top, 2),
        )
        if key[3] <= 0 or key[4] <= 0 or key in seen:
            continue
        seen.add(key)
        boxes.append(Box(page=page, x=key[1], y=key[2], width=key[3], height=key[4]))
        if len(boxes) == MAX_BOXES:
            break
    return boxes


async def run_synctex(workdir: Path, *args: str) -> list[dict[str, str]]:
    """Запускает synctex в workdir и возвращает записи его ответа.

    Как сборка: без shell, в своей группе процессов, с таймаутом и лимитом на размер файлов —
    вывод идёт в файл. Из окружения — только PATH: команду из SYNCTEX_EDITOR или
    SYNCTEX_VIEWER synctex выполнил бы сам.
    """
    output = workdir / STDOUT_NAME
    output_fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        process = await asyncio.create_subprocess_exec(
            "prlimit",
            f"--fsize={MAX_STDOUT_BYTES}",
            "--",
            "synctex",
            *args,
            cwd=workdir,
            env={"PATH": os.environ.get("PATH", os.defpath)},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=output_fd,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        os.close(output_fd)
    try:
        exit_code = await asyncio.wait_for(process.wait(), SYNCTEX_TIMEOUT_S)
    except TimeoutError:
        raise SyncTexRunError(f"synctex не ответил за {SYNCTEX_TIMEOUT_S} с") from None
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
    if exit_code != 0:
        # Например, вывод превысил MAX_STDOUT_BYTES — тогда synctex убивает SIGXFSZ.
        raise SyncTexRunError(f"synctex завершился с кодом {exit_code}")
    text = await asyncio.to_thread(output.read_text, encoding="utf-8", errors="replace")
    return parse_output(text)


@asynccontextmanager
async def _workdir() -> AsyncIterator[Path]:
    path = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="synctex-"))
    try:
        yield path
    finally:
        await asyncio.to_thread(shutil.rmtree, path, True)


async def edit(synctex: IO[bytes], page: int, x: float, y: float) -> Source | None:
    """Что написано в точке (x, y) страницы page; None — здесь нет текста студента."""
    async with _workdir() as workdir:
        await asyncio.to_thread(prepare_synctex, synctex, workdir)
        records = await run_synctex(workdir, "edit", "-o", f"{page}:{x:.4f}:{y:.4f}:{PDF_NAME}")
    return find_source(records)


async def view(synctex: IO[bytes], path: str, line: int) -> list[Box]:
    """Где в PDF строка line файла path. path проверен заранее: в нём нет двоеточия —
    разделителя полей в аргументе -i."""
    async with _workdir() as workdir:
        await asyncio.to_thread(prepare_synctex, synctex, workdir)
        records = await run_synctex(workdir, "view", "-i", f"{line}:0:{path}", "-o", PDF_NAME)
    return find_boxes(records)
