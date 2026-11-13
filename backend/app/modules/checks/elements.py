"""Рисунки, таблицы, листинги и ссылки на них (docs/checks.md): caption-missing,
caption-format, ref-broken, ref-missing, ref-after, listing-too-long."""

import re
from collections import defaultdict
from collections.abc import Iterator

from app.modules.checks.context import (
    Context,
    Found,
    ends_with_period,
    join_problems,
    shorten,
    starts_lowercase,
)
from app.modules.checks.report import Element, Ref
from app.modules.projects.tools import split_lines

CAPTION_EMPTY = (
    "У {kind} нет подписи: в PDF после номера пусто — «{number} N – ». Напишите, что на нём, "
    "с прописной буквы — или попросите ИИ."
)
BARE_IMAGE = (
    "Картинка {path} вставлена без подписи и номера. Попросите ИИ оформить её как рисунок "
    "с подписью."
)
BARE_TABLE = "Таблица вставлена без подписи и номера. Попросите ИИ добавить подпись."
BARE_CODE = "Код вставлен без подписи и номера. Попросите ИИ оформить его как листинг с подписью."
CAPTION_FORMAT = "Подпись «{caption}»: {problems}."
REF_NO_LABEL = (
    "В PDF здесь «??» вместо номера: ссылка ведёт на рисунок, таблицу или листинг, которого "
    "нет. Попросите ИИ исправить ссылку."
)
REF_NO_SOURCE = (
    "В PDF здесь «[?]»: источника «{key}» нет в списке источников. Попросите ИИ добавить "
    "источник из материалов или убрать ссылку."
)
REF_REPEATED = (
    "Одна метка «{label}» у двух элементов (строки {first} и {second}): ссылки на второй "
    "покажут номер первого. Попросите ИИ исправить метку."
)
REF_MISSING = (
    "На {kind} «{caption}» нет ссылки в тексте. По правилам на каждый ссылаются: «на рисунке "
    "3.1», «в таблице 3.1». Попросите ИИ добавить ссылку."
)
REF_MISSING_APPENDIX = (
    "На приложение «{title}» нет ссылки в тексте, например «(приложение А)». Попросите ИИ "
    "добавить ссылку."
)
REF_MISSING_FORMULA = (
    "У формулы есть номер, но ссылки на неё нет. Формулы без ссылок пишут без номера. "
    "Попросите ИИ убрать номер или сослаться на формулу."
)
REF_MISSING_SOURCE = (
    "На источник «{entry}» нет ссылки в тексте. Попросите ИИ добавить ссылку или убрать источник."
)
REF_AFTER = (
    "Ссылка на {kind} «{caption}» стоит после него. По правилам сначала пишут «Окно показано "
    "на рисунке 3.1», потом ставят сам рисунок. Попросите ИИ переставить."
)
LISTING_TOO_LONG = (
    "Листинг «{caption}» — {lines} строк. В тексте оставляют до 40 строк главного кода, а весь "
    "код переносят в приложение и ссылаются на него. Попросите ИИ перенести код в приложение."
)

# Длиннее этого листинг в основной части — предупреждение.
MAX_LISTING_LINES = 40
_GENITIVE = {"figure": "рисунка", "table": "таблицы", "listing": "листинга"}
_ACCUSATIVE = {"figure": "рисунок", "table": "таблицу", "listing": "листинг"}
_NUMBER_WORD = {"figure": "Рисунок", "table": "Таблица", "listing": "Листинг"}
_CAPTIONED = ("figure", "table", "listing")
# Подпись с номером внутри: «Рисунок 1 – Окно», «Таблица – Время».
_NUMBERED = re.compile(
    r"^(?:Рисунок|Рис\.|Таблица|Листинг)\s*(?:\d+(?:[.,]\d+)*\s*(?:[-–—]+)?|[-–—]+)"
)


def caption_missing(context: Context) -> Iterator[Found]:
    report = context.report
    for element in report.elements:
        if element.kind not in _CAPTIONED:
            continue
        if element.caption is None or not report.show(element.caption):
            kind = element.kind
            message = CAPTION_EMPTY.format(kind=_GENITIVE[kind], number=_NUMBER_WORD[kind])
            yield context.at("caption-missing", element.start, message)
    for bare in report.bare:
        if bare.kind == "image":
            message = BARE_IMAGE.format(path=bare.path)
        elif bare.kind == "table":
            message = BARE_TABLE
        else:
            message = BARE_CODE
        yield context.at("caption-missing", bare.start, message)


def caption_format(context: Context) -> Iterator[Found]:
    report = context.report
    for element in report.elements:
        if element.kind not in _CAPTIONED or element.caption is None:
            continue
        caption = report.show(element.caption)
        if not caption:
            continue
        problems = []
        if starts_lowercase(caption):
            problems.append("начните с прописной буквы")
        if ends_with_period(caption):
            problems.append("уберите точку в конце")
        if numbered := _NUMBERED.match(caption):
            problems.append(f"уберите «{numbered[0].strip()}» — номер ставится сам")
        if problems:
            message = CAPTION_FORMAT.format(caption=caption, problems=join_problems(problems))
            yield context.at("caption-format", element.start, message)


def ref_broken(context: Context) -> Iterator[Found]:
    report = context.report
    defined = {label.key for label in report.labels}
    sources = {item.key for item in report.bibitems}
    for ref in report.refs:
        if ref.kind == "label" and ref.key not in defined:
            yield context.at("ref-broken", ref.start, REF_NO_LABEL)
        elif ref.kind == "cite" and ref.key not in sources:
            yield context.at("ref-broken", ref.start, REF_NO_SOURCE.format(key=ref.key))
    # Метки и ключи источников — разные имена: \label{a} и \bibitem{a} не повтор.
    yield from _repeats(context, [(label.key, label.start) for label in report.labels])
    yield from _repeats(context, [(item.key, item.start) for item in report.bibitems])


def _repeats(context: Context, definitions: list[tuple[str, int]]) -> Iterator[Found]:
    """Второе и следующие определения одного имени — со строкой первого."""
    first_at: dict[str, int] = {}
    for key, start in sorted(definitions, key=lambda definition: definition[1]):
        if key not in first_at:
            first_at[key] = start
            continue
        first = context.report.locate(first_at[key])[1]
        second = context.report.locate(start)[1]
        message = REF_REPEATED.format(label=key, first=first, second=second)
        yield context.at("ref-broken", start, message)


def _refs_by_key(refs: list[Ref], kind: str) -> dict[str, list[Ref]]:
    result: dict[str, list[Ref]] = defaultdict(list)
    for ref in refs:
        if ref.kind == kind:
            result[ref.key].append(ref)
    return result


def _outside(element: Element, refs: list[Ref]) -> list[Ref]:
    """Ссылки на элемент, кроме ссылок из его собственной подписи."""
    return [ref for ref in refs if not element.start <= ref.start < element.end]


def ref_missing(context: Context) -> Iterator[Found]:
    report = context.report
    labels = _refs_by_key(report.refs, "label")
    for element in report.elements:
        if element.kind == "formula" and not element.numbered:
            continue
        if element.label is not None and _outside(element, labels.get(element.label, [])):
            continue
        caption = report.show(element.caption) if element.caption else ""
        if element.kind == "appendix":
            message = REF_MISSING_APPENDIX.format(title=caption)
        elif element.kind == "formula":
            message = REF_MISSING_FORMULA
        else:
            message = REF_MISSING.format(kind=_ACCUSATIVE[element.kind], caption=caption)
        yield context.at("ref-missing", element.start, message)
    cites = _refs_by_key(report.refs, "cite")
    for item in report.bibitems:
        if not cites.get(item.key):
            entry = shorten(report.show(item.text))
            yield context.at("ref-missing", item.start, REF_MISSING_SOURCE.format(entry=entry))


def ref_after(context: Context) -> Iterator[Found]:
    report = context.report
    labels = _refs_by_key(report.refs, "label")
    for element in report.elements:
        if element.kind not in _CAPTIONED or element.label is None:
            continue
        refs = _outside(element, labels.get(element.label, []))
        if refs and min(ref.start for ref in refs) > element.start:
            caption = report.show(element.caption) if element.caption else ""
            message = REF_AFTER.format(kind=_ACCUSATIVE[element.kind], caption=caption)
            yield context.at("ref-after", element.start, message)


def listing_too_long(context: Context) -> Iterator[Found]:
    report = context.report
    texts = context.snapshot.texts
    for element in report.elements:
        if element.kind != "listing" or report.in_appendix(element.start):
            continue
        if element.code is not None:
            lines = count_lines(report.source[element.code.start : element.code.end])
        elif element.path is not None and element.path in texts:
            lines = len(split_lines(texts[element.path]))
        else:
            continue
        if lines > MAX_LISTING_LINES:
            caption = report.show(element.caption) if element.caption else ""
            message = LISTING_TOO_LONG.format(caption=caption, lines=lines)
            yield context.at("listing-too-long", element.start, message)


def count_lines(code: str) -> int:
    """Строки кода окружения: от строки после \\begin до \\end, пустые тоже считаются."""
    return len(split_lines(code))
