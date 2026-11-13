"""Оформление текста (docs/checks.md): heading-format, list-format, formula-format,
bib-order, manual-formatting."""

import re
from collections.abc import Iterator, Mapping

from app.modules.checks.context import (
    Context,
    Found,
    ends_with_period,
    join_problems,
    shorten,
    starts_lowercase,
)

HEADING_FORMAT = "Заголовок «{title}»: {problems}."
HEADING_TOO_DEEP = (
    "Заголовок «{title}» — четвёртый уровень, а по правилам их не больше трёх (3.1.2). "
    "Попросите ИИ сделать его подразделом или обычным абзацем."
)
LIST_FORMAT = "Пункт «{start}»: {problems}."
FORMULA_FORMAT = "Пояснение к формуле начинают словом «где» — {problems}. Попросите ИИ исправить."
BIB_ORDER = (
    "Источники должны идти в порядке первой ссылки в тексте. «{entry}» стоит {actual}-м, "
    "а сослались на него {expected}-м. Попросите ИИ переставить источники."
)
MANUAL_PACKAGE = (
    "Подключён пакет «{name}». Оформление задаёт шаблон, пакеты для него не нужны. Если пакет "
    "нужен для формул или особых символов — оставьте его."
)
MANUAL_COMMAND = (
    "Оформление задано вручную ({command}): из-за этого отчёт может разойтись с правилами "
    "по полям, шрифту, отступам или разрывам страниц. Попросите ИИ убрать команду."
)

_HEADINGS = {"section", "subsection", "subsubsection"}
_DEEP = {"paragraph", "subparagraph"}
_WORD = re.compile(r"[^\W\d_]+")
_PACKAGES = {"usepackage", "RequirePackage"}
_MANUAL = {
    "geometry", "newgeometry", "setlength", "addtolength", "linespread", "fontsize",
    "selectfont", "setmainfont", "newpage", "clearpage", "pagebreak", "vspace", "vskip",
    "hspace", "noindent", "tiny", "scriptsize", "footnotesize", "small", "normalsize",
    "large", "Large", "LARGE", "huge", "Huge", "color", "textcolor",
}  # fmt: skip


def heading_format(context: Context) -> Iterator[Found]:
    report = context.report
    body = report.body
    for heading in report.headings:
        if not body.start <= heading.start < body.end:
            continue
        title = report.show(heading.title)
        if heading.name in _DEEP:
            yield context.at("heading-format", heading.start, HEADING_TOO_DEEP.format(title=title))
            continue
        problems = []
        if starts_lowercase(title):
            problems.append("начните с прописной буквы")
        if ends_with_period(title):
            problems.append("уберите точку в конце")
        if problems:
            message = HEADING_FORMAT.format(title=title, problems=join_problems(problems))
            yield context.at("heading-format", heading.start, message)


def list_format(context: Context) -> Iterator[Found]:
    report = context.report
    for items in report.lists:
        for index, item in enumerate(items):
            text = report.show(item.text)
            if not text:
                continue
            problems = []
            # Прописная кириллическая и за ней строчная: аббревиатуры (СУБД) и латиница
            # (SQL-запрос) не считаются.
            if _capitalized(text):
                problems.append("начните со строчной буквы")
            last = text[-1]
            if index == len(items) - 1:
                if last != ".":
                    problems.append("поставьте «.» в конце — это последний пункт")
            elif last != ";" and not (item.nested and last == ":"):
                problems.append("поставьте «;» в конце")
            if problems:
                message = LIST_FORMAT.format(start=shorten(text), problems=join_problems(problems))
                yield context.at("list-format", item.start, message)


def _capitalized(text: str) -> bool:
    if len(text) < 2:
        return False
    first, second = text[0], text[1]
    return ("А" <= first <= "Я" or first == "Ё") and second.isalpha() and second.islower()


def formula_format(context: Context) -> Iterator[Found]:
    report = context.report
    plain = report.plain
    texts = context.snapshot.texts
    for end in report.formula_ends:
        position = end
        while position < len(plain) and plain[position].isspace():
            position += 1
        word = _WORD.match(plain, position)
        if word is None or word[0].lower() != "где":
            continue
        problems = []
        if plain[word.end() :].lstrip(" \t").startswith(":"):
            problems.append("без двоеточия")
        if word[0][0].isupper():
            problems.append("со строчной буквы")
        if _blank_line_between(report.locate(end - 1), report.locate(position), texts):
            problems.append("сразу под формулой, без пустой строки")
        if problems:
            message = FORMULA_FORMAT.format(problems=join_problems(problems))
            yield context.at("formula-format", position, message)


def _blank_line_between(
    formula: tuple[str, int], word: tuple[str, int], texts: Mapping[str, str]
) -> bool:
    """Есть ли пустая строка между концом формулы и «где». Смотрится исходный файл:
    строка из одного комментария не пустая — LaTeX не начнёт с неё абзац."""
    file, line = formula
    word_file, word_line = word
    text = texts.get(file)
    if file != word_file or text is None:
        return False
    lines = text.split("\n")
    return any(not lines[number - 1].strip() for number in range(line + 1, word_line))


def bib_order(context: Context) -> Iterator[Found]:
    report = context.report
    first_cite: dict[str, int] = {}
    for ref in report.refs:
        if ref.kind == "cite" and ref.key not in first_cite:
            first_cite[ref.key] = ref.start
    # Источники без ссылок в сравнении не участвуют: их ловит ref-missing.
    cited = [item for item in report.bibitems if item.key in first_cite]
    expected = sorted(cited, key=lambda item: first_cite[item.key])
    for index, item in enumerate(cited):
        if item.key != expected[index].key:
            entry = shorten(report.show(item.text))
            place = next(i for i, other in enumerate(expected) if other.key == item.key)
            message = BIB_ORDER.format(entry=entry, actual=index + 1, expected=place + 1)
            yield context.at("bib-order", item.start, message)
            return


def manual_formatting(context: Context) -> Iterator[Found]:
    report = context.report
    for command in report.commands:
        if command.name in _PACKAGES:
            names = ""
            if command.argument is not None:
                text = report.source[command.argument.start : command.argument.end]
                names = ", ".join(name.strip() for name in text.split(",") if name.strip())
            yield context.at("manual-formatting", command.start, MANUAL_PACKAGE.format(name=names))
        elif command.name in _MANUAL:
            message = MANUAL_COMMAND.format(command=f"\\{command.name}")
            yield context.at("manual-formatting", command.start, message)
