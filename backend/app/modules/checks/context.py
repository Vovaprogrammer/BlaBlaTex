"""Что нужно проверкам: снимок проекта, итог сборки и общие правила (docs/checks.md).

Снимок собирают реализации ProjectTools — из базы (checks/service.py) или из памяти
(фейк для тестов): проверки сами ни в базу, ни в хранилище не ходят. Поэтому один и тот
же проект всегда даёт одни и те же находки.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

from app.modules.builds.log_parser import ParsedLog, parse_log
from app.modules.checks.report import Report, read_report
from app.modules.checks.schemas import CheckId, CheckPlace
from app.modules.projects.schemas import Engine

MaterialStatus = Literal["pending", "ready", "failed"]

# Пробельные символы подряд, включая переводы строк, — один пробел (сверка с материалами).
_WHITESPACE = re.compile(r"\s+")
# Число в тексте: «число.число.число» (дата, версия, адрес) — одно число; группы по три
# цифры — через ~, \, или неразрывный пробел; одна дробная часть — через «,» или «.».
NUMBER = re.compile(r"\d+(?:\.\d+){2,}|\d{1,3}(?:(?:~|\\,| )\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
_DOTTED = re.compile(r"\d+(?:\.\d+){2,}")
_GROUP_SEPARATOR = re.compile(r"~|\\,| ")
# Сколько символов показывать из начала записи, пункта или строки кода.
SHORT_TEXT = 40
LONG_TEXT = 80


@dataclass(frozen=True)
class SectionSpec:
    """Раздел шаблона: название, файл и обязателен ли он (required в template.yaml)."""

    title: str
    file: str
    required: bool


@dataclass(frozen=True)
class MaterialSource:
    """Материал из materials/: статус разбора, извлечённый текст и описание картинки."""

    path: str
    status: MaterialStatus
    text: str | None
    description: str | None


@dataclass(frozen=True)
class Snapshot:
    """Проект на один момент — всё, по чему проверяется исходник."""

    main_file: str
    sections: tuple[SectionSpec, ...]
    # Текстовые файлы проекта, путь → содержимое: исходники, meta.tex и код из материалов.
    texts: Mapping[str, str]
    # Пути всех файлов проекта, без папок: для file-missing.
    files: frozenset[str]
    materials: tuple[MaterialSource, ...]
    # Значения полей проекта и профиля: числа из них не считаются выдуманными.
    values: tuple[str, ...]
    # Ключи полей шаблона: какие поля титульного листа студент может заполнить.
    field_keys: frozenset[str]
    engine: Engine = "xelatex"


@dataclass(frozen=True)
class BuildOutcome:
    """Законченная сборка текущих файлов: итог, число ошибок и лог (если сборка до него
    дошла)."""

    status: Literal["ok", "error", "timeout"]
    errors: int
    log: bytes | None


@dataclass(frozen=True)
class Found:
    """Находка до сортировки: position — место в Report.source, по нему находки одной
    строки идут по порядку."""

    check: CheckId
    message: str
    file: str | None = None
    line: int | None = None
    position: int = 0
    place: CheckPlace = "file"
    field: str | None = None


class Context:
    """Снимок, итог сборки и то, что из них считается один раз на все проверки."""

    def __init__(self, snapshot: Snapshot, build: BuildOutcome | None) -> None:
        self.snapshot = snapshot
        self.build = build

    @cached_property
    def report(self) -> Report:
        return read_report(self.snapshot.main_file, self.snapshot.texts)

    def at(self, check: CheckId, position: int, message: str) -> Found:
        """Находка в месте position отчёта: файл и строка — по позиции."""
        file, line = self.report.locate(position)
        return Found(check, message, file, line, position)

    @cached_property
    def material_text(self) -> str:
        """Текст всех прочитанных материалов и описания картинок — для поиска строк кода.

        Пробельные символы подряд — один пробел; материалы разделены нулевым символом,
        которого нет ни в строке кода, ни в тексте: строка не найдётся на стыке двух файлов.
        """
        return "\x00".join(_WHITESPACE.sub(" ", text) for text in self._material_texts)

    @cached_property
    def material_numbers(self) -> frozenset[str]:
        """Числа из материалов, описаний картинок и значений полей, нормализованные."""
        numbers: set[str] = set()
        for text in (*self._material_texts, *self.snapshot.values):
            numbers.update(normalize_number(match[0]) for match in NUMBER.finditer(text))
        return frozenset(numbers)

    @cached_property
    def _material_texts(self) -> list[str]:
        texts: list[str] = []
        for material in self.snapshot.materials:
            if material.status == "ready" and material.text:
                texts.append(material.text)
            if material.description:
                texts.append(material.description)
        return texts

    @cached_property
    def unread_note(self) -> str:
        """Дописка к находкам сверки, если часть материалов ещё не прочитана."""
        unread = [
            material.path for material in self.snapshot.materials if material.status != "ready"
        ]
        if not unread:
            return ""
        return f" Сверка неполная: не прочитаны {', '.join(unread)}."

    @cached_property
    def parsed_log(self) -> ParsedLog | None:
        if self.build is None or self.build.log is None:
            return None
        return parse_log(self.build.log, dict(self.snapshot.texts), self.snapshot.engine)


def normalize_number(text: str) -> str:
    """Число для сравнения: группы склеены, «,» → «.», нули в конце дробной части убраны.

    «0,0410» = «0.041», «10~000» = «10000»; «3.12.1» сравнивается как строка.
    """
    if _DOTTED.fullmatch(text):
        return text
    digits = _GROUP_SEPARATOR.sub("", text).replace(",", ".")
    whole, dot, fraction = digits.partition(".")
    fraction = fraction.rstrip("0")
    return f"{whole}.{fraction}" if dot and fraction else whole


def shorten(text: str, limit: int = SHORT_TEXT) -> str:
    """Начало текста для находки: не длиннее limit символов, по границе слова, с «…»."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def starts_lowercase(text: str) -> bool:
    """Первая буква текста — строчная кириллическая. Латиница не считается: «pandas» —
    имя библиотеки."""
    letter = next((char for char in text if char.isalpha()), None)
    return letter is not None and ("а" <= letter <= "я" or letter == "ё")


def ends_with_period(text: str) -> bool:
    """Последний символ — точка, и это не многоточие."""
    return text.endswith(".") and not text.endswith("..")


def join_problems(problems: list[str]) -> str:
    return ", ".join(problems)
