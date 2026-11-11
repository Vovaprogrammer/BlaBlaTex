"""Имя отчёта для PDF и архива (architecture.md 9.1, «Имя отчёта»): «ЛР3_Чистяков».

Имя видит студент в папке «Загрузки» и преподаватель, которому отчёт отправили. Поэтому
оно открывается в Windows, macOS и Linux: без запрещённых в Windows символов и имён.
"""

import unicodedata
from collections.abc import Mapping

from app.modules.templates.meta import one_line

WORK_TYPE_KEY = "work_type"
LAB_NUMBER_KEY = "lab_number"
# Вид работы — сокращение. Поля нет — лабораторная: так у шаблонов без выбора вида.
WORK_TYPE_ABBREVIATIONS = {"Лабораторная работа": "ЛР", "Практическая работа": "ПР"}
DEFAULT_ABBREVIATION = "ЛР"
DEFAULT_NAME = "Отчёт"
TITLE_MAX_LENGTH = 60
NAME_MAX_LENGTH = 100
# Байты UTF-8: предел имени в Linux и macOS — 255, остаток — расширению и запасу.
NAME_MAX_BYTES = 200

_FORBIDDEN = frozenset('\\/:*?"<>|')
_INVISIBLE = frozenset(("Cc", "Cf"))
# Имена устройств Windows: с ними файл не создать, даже с расширением (CON.pdf).
_RESERVED = frozenset(
    (
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{n}" for n in range(1, 10)),
        *(f"LPT{n}" for n in range(1, 10)),
    )
)


def report_name(*, kind: str, title: str, fields: Mapping[str, str | int], last_name: str) -> str:
    """Имя отчёта без расширения.

    Лабораторная — вид работы, номер и фамилия: «ЛР3_Чистяков»; нет номера — «ЛР_Чистяков»,
    нет фамилии — «ЛР3». Другие виды, шаблоны и неизвестный вид работы — название проекта
    (первые 60 символов) и фамилия.
    """
    stem = _lab_stem(kind, fields)
    if stem is None:
        stem = one_line(title)[:TITLE_MAX_LENGTH]
    parts = (stem.strip(), one_line(last_name))
    return safe_filename("_".join(part for part in parts if part))


def safe_filename(name: str) -> str:
    """Имя файла, которое откроется в Windows, macOS и Linux.

    Символы \\ / : * ? " < > |, управляющие и невидимые — _; пробелы подряд — один; точки
    и пробелы по краям убираются; не длиннее 100 символов и 200 байт UTF-8. Имя устройства
    Windows (CON, NUL, COM1…) получает _ сразу после себя: «CON_». Пустое — «Отчёт».
    """
    chars = (
        "_" if char in _FORBIDDEN or unicodedata.category(char) in _INVISIBLE else char
        for char in name
    )
    text = _trim(" ".join("".join(chars).split()))
    text = _trim(text[:NAME_MAX_LENGTH])
    while len(text.encode()) > NAME_MAX_BYTES:
        text = _trim(text[:-1])
    base, dot, rest = text.partition(".")
    if base.upper() in _RESERVED:
        text = f"{base}_{dot}{rest}"
    return text or DEFAULT_NAME


def _lab_stem(kind: str, fields: Mapping[str, str | int]) -> str | None:
    """«ЛР3» или «ПР» для лабораторной; None — имя строится из названия."""
    if kind != "lab":
        return None
    work_type = fields.get(WORK_TYPE_KEY)
    if work_type is None:
        abbreviation = DEFAULT_ABBREVIATION
    else:
        found = WORK_TYPE_ABBREVIATIONS.get(one_line(str(work_type)))
        if found is None:
            return None
        abbreviation = found
    number = fields.get(LAB_NUMBER_KEY)
    return abbreviation if number is None else f"{abbreviation}{one_line(str(number))}"


def _trim(text: str) -> str:
    return text.strip(" .")
