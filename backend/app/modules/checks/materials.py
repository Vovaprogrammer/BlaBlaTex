"""Файлы и сверка с материалами (docs/checks.md): file-missing, code-not-in-materials,
number-not-in-materials. Эти проверки защищают от выдумок ИИ."""

import re
from bisect import bisect_right
from collections.abc import Iterator
from pathlib import PurePosixPath

from app.modules.checks.context import (
    LONG_TEXT,
    NUMBER,
    Context,
    Found,
    normalize_number,
    shorten,
)
from app.modules.checks.report import Span
from app.modules.projects.paths import is_material_path
from app.modules.projects.service import MATERIAL_DOCUMENT_EXTENSIONS
from app.modules.projects.tools import split_lines

FILE_MISSING = (
    "Файла {path} нет в проекте — PDF не соберётся. Если это ваш скриншот или код, загрузите "
    "его в материалы. Если ИИ ошибся в имени, попросите выбрать файл из материалов."
)
FILE_SIMILAR = " Похожий файл: {path}."
FILE_NOT_IN_BUILD = (
    "{path} нельзя вставить в отчёт: PDF и документы из материалов читает только ИИ. "
    "Сохраните картинку как PNG или JPG и загрузите её."
)
FILE_SVG = "Картинки SVG не вставляются. Сохраните {path} как PNG и загрузите."
CODE_NOT_IN_MATERIALS = (
    "{missing} из {checked} строк листинга «{caption}» нет в ваших материалах, например "
    "«{line}». Если это вывод программы или ваш код, ИИ мог его придумать: сверьте "
    "с настоящим и загрузите его в материалы — файлом или скриншотом."
)
NUMBER_NOT_IN_MATERIALS = (
    "Чисел {numbers} нет в ваших материалах. Если это результаты, ИИ мог их придумать или "
    "посчитать сам: сверьте с выводом программы и скриншотами."
)

# Картинка без расширения: сборка ищет такие файлы.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")
# Строка кода короче — не сверяется: «}», «end».
MIN_CODE_LINE = 4
_SPACES = re.compile(r"[ \t]+")
# Строка-пропуск в листинге: «# ...», «// …».
_GAP_MARKS = re.compile(r"#|//|--|/\*|\*/|\s")
_GAP = re.compile(r"[.…]+")


def file_missing(context: Context) -> Iterator[Found]:
    files = context.snapshot.files
    for use in context.report.uses:
        path = use.path
        candidates = [path]
        if use.kind == "image" and not PurePosixPath(path).suffix:
            candidates = [path + extension for extension in IMAGE_EXTENSIONS]
        found = next((candidate for candidate in candidates if candidate in files), None)
        if found is not None:
            suffix = PurePosixPath(found).suffix.lower()
            if is_material_path(found) and suffix in MATERIAL_DOCUMENT_EXTENSIONS:
                yield context.at("file-missing", use.start, FILE_NOT_IN_BUILD.format(path=found))
            elif use.kind == "image" and suffix == ".svg":
                yield context.at("file-missing", use.start, FILE_SVG.format(path=found))
            continue
        message = FILE_MISSING.format(path=path)
        # Сборка идёт в Linux, регистр важен; файл, который отличается только им, — подсказка.
        lowered = {candidate.lower() for candidate in candidates}
        similar = next((file for file in sorted(files) if file.lower() in lowered), None)
        if similar is not None:
            message += FILE_SIMILAR.format(path=similar)
        yield context.at("file-missing", use.start, message)


def code_not_in_materials(context: Context) -> Iterator[Found]:
    report = context.report
    texts = context.snapshot.texts
    for element in report.elements:
        if element.kind != "listing":
            continue
        if element.code is not None:
            code = report.source[element.code.start : element.code.end]
            file, first_line = report.locate(element.code.start)
            position = element.code.start
        elif element.path is not None and not is_material_path(element.path):
            # Файл из materials/ — это и есть материал.
            if element.path not in texts:
                continue
            code, file, first_line, position = texts[element.path], element.path, 1, 0
        else:
            continue
        checked = 0
        missing: list[tuple[int, str]] = []
        for index, raw in enumerate(split_lines(code)):
            line = _SPACES.sub(" ", raw).strip()
            if len(line) < MIN_CODE_LINE or _GAP.fullmatch(_GAP_MARKS.sub("", line)):
                continue
            checked += 1
            if line not in context.material_text:
                missing.append((index, line))
        if not missing:
            continue
        index, line = missing[0]
        caption = report.show(element.caption) if element.caption else ""
        message = CODE_NOT_IN_MATERIALS.format(
            missing=len(missing), checked=checked, caption=caption, line=shorten(line, LONG_TEXT)
        )
        yield Found(
            "code-not-in-materials",
            message + context.unread_note,
            file,
            first_line + index,
            position,
        )


def number_not_in_materials(context: Context) -> Iterator[Found]:
    report = context.report
    source = report.source
    plain = report.plain
    skipped = sorted([(span.start, span.end) for span in (*report.math, *report.bibliography)])
    starts = [start for start, _ in skipped]
    # Наибольший конец среди куска и всех до него: куски бывают вложенными.
    reach: list[int] = []
    for _, end in skipped:
        reach.append(max(end, reach[-1]) if reach else end)
    known = context.material_numbers
    by_line: dict[tuple[str, int], tuple[int, list[str]]] = {}
    for match in NUMBER.finditer(source, report.body.start, report.body.end):
        start = match.start()
        if plain[start] == " ":
            continue
        # Перед числом буква, цифра или «_» — это часть имени: x86, int32.
        if start > 0 and (source[start - 1].isalnum() or source[start - 1] == "_"):
            continue
        index = bisect_right(starts, start) - 1
        if index >= 0 and reach[index] > start:
            continue
        number = normalize_number(match[0])
        if number.isdigit() and int(number) < 10:
            continue
        if number in known:
            continue
        place = report.locate(start)
        shown = report.show(Span(start, match.end())) or match[0]
        _, numbers = by_line.setdefault(place, (start, []))
        if shown not in numbers:
            numbers.append(shown)
    for (file, line), (position, numbers) in by_line.items():
        message = NUMBER_NOT_IN_MATERIALS.format(numbers="; ".join(numbers))
        yield Found("number-not-in-materials", message + context.unread_note, file, line, position)
