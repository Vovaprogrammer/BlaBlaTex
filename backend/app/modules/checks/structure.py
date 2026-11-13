"""Структура и титул: section-empty, placeholder, title-empty (docs/checks.md)."""

import re
from collections.abc import Iterator

from app.modules.checks.context import Context, Found
from app.modules.checks.report import Span, group, optional
from app.modules.templates.registry import META_FILE

SECTION_EMPTY = (
    "Раздел «{title}» пустой. Попросите ИИ заполнить его по материалам. Если ИИ не нашёл, "
    "из чего писать, — загрузите методичку или задание."
)
SECTION_MISSING = (
    "Раздела «{title}» нет в отчёте: файл {file} удалён или не подключён. "
    "Попросите ИИ вернуть раздел."
)
PLACEHOLDER = (
    "В тексте осталась заглушка «{fragment}». Замените её настоящим текстом или попросите "
    "ИИ дописать это место по материалам."
)
TITLE_FROM_PROFILE = (
    "На титульном листе нет {what}. Заполните это в профиле — титульник обновится сам."
)
TITLE_FROM_FIELDS = "На титульном листе нет поля «{name}». Заполните его в полях работы{example}."
TEACHER_EXAMPLE = " — например, преподаватель «доц. Петров П. П.»"

# Что не делает раздел непустым: заголовки с аргументами и метки.
_SKIPPED = re.compile(r"\\(?:(?:sub){0,2}section\*?|label)(?![A-Za-z@])")
_PLACEHOLDER_WORDS = re.compile(r"(?<!\w)(?:TODO|FIXME|TBD)(?!\w)|lorem\s+ipsum", re.IGNORECASE)
_PLACEHOLDER_XXX = re.compile(r"(?<!\w)XXX(?!\w)")
_QUESTIONS = re.compile(r"\?{3,}")
_BRACKETED = re.compile(r"\[[^\[\]\n]{1,200}\]|<[^<>\n]{1,200}>")
_FIRST_WORD = re.compile(r"\s*([^\W\d_]+)")
_PLACEHOLDER_STARTS = {
    "вставьте", "вставить", "добавьте", "добавить", "укажите", "указать", "заполните",
    "заполнить", "опишите", "описать", "впишите", "здесь", "сюда", "ваш", "ваша", "ваше",
    "ваши",
}  # fmt: skip
_PLACEHOLDER_COMMANDS = {"lipsum", "blindtext", "Blindtext"}

_TITLE_PAGE = re.compile(r"\\bbtTitlePage(?![A-Za-z@])")
_DEFINITION = re.compile(r"^\\def\\bbt([A-Za-z]+)\{(.*)\}\s*$", re.MULTILINE)
# Поля титульного листа (title-empty): макрос, где исправлять, ключ поля и как его назвать.
_TITLE_FIELDS = (
    ("ShortName", "profile", "last_name", "ФИО"),
    ("Group", "profile", "group_name", "группы"),
    ("Department", "profile", "department", "кафедры"),
    ("Discipline", "fields", "discipline", "Дисциплина"),
    ("LabNumber", "fields", "lab_number", "Номер работы"),
    ("LabTitle", "fields", "lab_title", "Тема работы"),
    ("Teacher", "fields", "teacher", "Преподаватель"),
)


def section_empty(context: Context) -> Iterator[Found]:
    report = context.report
    main = context.snapshot.main_file
    for section in context.snapshot.sections:
        if not section.required:
            continue
        code = report.file_code(section.file)
        if code is None or section.file not in report.files:
            message = SECTION_MISSING.format(title=section.title, file=section.file)
            yield Found("section-empty", message, main)
        elif not _has_content(code):
            message = SECTION_EMPTY.format(title=section.title)
            yield Found("section-empty", message, section.file, 1)


def _has_content(code: str) -> bool:
    """Осталось ли что-то, кроме заголовков, меток и пробелов (комментарии уже убраны)."""
    cursor = 0
    for match in _SKIPPED.finditer(code):
        if match.start() < cursor:
            continue
        if code[cursor : match.start()].strip():
            return True
        position = match.end()
        short = optional(code, position)
        if short is not None:
            position = short.end + 1
        argument = group(code, position)
        cursor = argument.end + 1 if argument is not None else position
    return bool(code[cursor:].strip())


def placeholder(context: Context) -> Iterator[Found]:
    report = context.report
    plain = report.plain
    body = report.body
    for pattern in (_PLACEHOLDER_WORDS, _PLACEHOLDER_XXX, _QUESTIONS):
        for match in pattern.finditer(plain, body.start, body.end):
            yield _placeholder(context, match.start(), match[0])
    for match in _BRACKETED.finditer(plain, body.start, body.end):
        word = _FIRST_WORD.match(match[0], 1)
        if word is not None and word[1].lower() in _PLACEHOLDER_STARTS:
            yield _placeholder(context, match.start(), report.show(Span(*match.span())))
    for command in report.commands:
        if command.name in _PLACEHOLDER_COMMANDS and body.start <= command.start < body.end:
            yield _placeholder(context, command.start, f"\\{command.name}")


def _placeholder(context: Context, position: int, fragment: str) -> Found:
    return context.at("placeholder", position, PLACEHOLDER.format(fragment=fragment))


def title_empty(context: Context) -> Iterator[Found]:
    snapshot = context.snapshot
    main = context.report.file_code(snapshot.main_file) or ""
    meta = snapshot.texts.get(META_FILE)
    if meta is None or not _TITLE_PAGE.search(main):
        return
    values = {match[1]: match[2] for match in _DEFINITION.finditer(meta)}
    for macro, place, key, name in _TITLE_FIELDS:
        value = values.get(macro)
        # Поля, которого нет в шаблоне, студенту не заполнить.
        if value is None or value.replace("~", " ").strip():
            continue
        if place == "profile":
            message = TITLE_FROM_PROFILE.format(what=name)
        elif key in snapshot.field_keys:
            example = TEACHER_EXAMPLE if key == "teacher" else ""
            message = TITLE_FROM_FIELDS.format(name=name, example=example)
        else:
            continue
        yield Found(
            "title-empty", message, place="profile" if place == "profile" else "fields", field=key
        )
