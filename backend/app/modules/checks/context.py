"""Что нужно проверкам: снимок проекта, итог сборки и общие правила (docs/checks.md).

Снимок собирают реализации ProjectTools — из базы (checks/service.py) или из памяти
(фейк для тестов): проверки сами ни в базу, ни в хранилище не ходят. Поэтому один и тот
же проект всегда даёт одни и те же находки.
"""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cached_property
from typing import Literal

from app.modules.builds.log_parser import ParsedLog, parse_log
from app.modules.checks.report import LineRange, Report, read_report
from app.modules.checks.schemas import CheckId, CheckPlace
from app.modules.projects.schemas import Engine

MaterialStatus = Literal["pending", "ready", "failed"]
# Фрагмент кода в отчёте: файл отчёта, файл кода и строки из \bbtCodeFile[lines=…].
type Listed = tuple[str, str, LineRange]

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
# Число в материале: как в тексте отчёта, но дробное — ещё и с порядком. «2.04e-05» так
# пишут замеры Python и JSON; иначе это были бы два числа, 2.04 и 05.
_MATERIAL_NUMBER = re.compile(
    r"\d+(?:\.\d+){2,}|\d{1,3}(?:(?:~|\\,|\xa0)\d{3})+(?:[.,]\d+)?"
    r"|\d+(?:[.,]\d+)?(?:[eE][+-]?\d{1,3})?"
)
# Число с нулём впереди («0410») — не отдельное число, а дробная часть «0,0410».
_LEADING_ZERO = re.compile(r"0\d")
# Сразу за числом с запятой — ещё одна дробная часть: соседние столбцы CSV склеились.
_GLUED_TAIL = re.compile(r"[.,]\d")
# Цифры, сцепленные запятыми и точками, где есть хотя бы одна запятая: «100,7234.3».
_COMMA_RUN = re.compile(r"\d+(?:[.,]\d+)*,\d+(?:[.,]\d+)*")
# Пересчёт единиц (с, мс, мкс): число из материала, умноженное на 10 в этой степени.
UNIT_POWERS = (3, 6, -3, -6)
# Округлённое или пересчитанное число засчитывается, если в нём столько значащих цифр:
# «0,009» подошло бы к любому числу от 0,0085 до 0,0095.
MIN_ROUNDED_DIGITS = 2
# Целое округлением — только из трёх цифр и больше («152 мс» из 0,15226 с): двузначные
# целые — обычно счётчики, у них совпадение с чужим замером было бы случайным.
MIN_ROUNDED_INTEGER_DIGITS = 3
# Проценты: доля из материала, умноженная на 100 (0,873 → 87,3 %).
PERCENT_POWER = 2
# Наносекунды в материалах: Java System.nanoTime, Python perf_counter_ns и time_ns, слово
# «наносекунд», «нс» или «ns» после числа, в скобках или в названии столбца («time_ns»,
# «Время, нс»). Просто «ns» не годится: так в коде называют список размеров.
_NANOSECONDS = re.compile(
    r"nano(?:time|seconds?)|_ns\b|наносекунд|\d\s?(?:ns|нс)\b|[(\[,]\s*нс\b|[(\[]ns[)\]]",
    re.IGNORECASE,
)
# Если наносекунды есть, целые числа материалов от стольких цифр пересчитываются из нс в мкс,
# мс и с: делятся на 10 в этих степенях.
MIN_NANOSECOND_DIGITS = 4
NANOSECOND_POWERS = (3, 6, 9)


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
    # Каким был файл кода, когда его фрагмент вставили в файл отчёта, — только если с тех
    # пор файл изменился. Берётся из истории правок; без истории (фейк) — пусто.
    listed_code: Mapping[Listed, str] = field(default_factory=dict)


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
    def material_numbers(self) -> "MaterialNumbers":
        """Числа из материалов, описаний картинок и значений полей."""
        return MaterialNumbers.read((*self._material_texts, *self.snapshot.values))

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


@dataclass(frozen=True)
class MaterialNumbers:
    """Числа материалов для number-not-in-materials (docs/checks.md): нормализованные записи
    и значения по возрастанию — по ним округление ищется двоичным поиском, без перебора."""

    exact: frozenset[str]
    values: list[Decimal]
    # Дробные значения: только их пересчитываем в другие единицы. Целые — счётчики
    # и размеры: после деления на 10⁶ они подходили бы к чему угодно.
    fractions: list[Decimal]
    # Целые от MIN_NANOSECOND_DIGITS цифр, если в материалах есть наносекунды, иначе пусто:
    # их пересчитываем из нс в мкс, мс и с.
    nanoseconds: list[Decimal]

    @classmethod
    def read(cls, texts: Iterable[str]) -> "MaterialNumbers":
        """Запятая между цифрами в материале — дробная часть («7234,3» из Excel по-русски)
        или разделитель столбцов («100,7234.3» из CSV через запятую): читаем оба варианта."""
        texts = list(texts)
        exact: set[str] = set()
        written: set[str] = set()
        for text in texts:
            columns = _COMMA_RUN.sub(_split_columns, text)
            for reading, separated in ((text, False), (columns, True)):
                for match in NUMBER.finditer(reading):
                    if _counts(match, separated):
                        exact.add(normalize_number(match[0]))
                for match in _MATERIAL_NUMBER.finditer(reading):
                    if _counts(match, separated):
                        written.add(match[0])
        values = sorted(_decimal(number) for number in written if not _DOTTED.fullmatch(number))
        fractions = [value for value in values if _places(value) > 0]
        nanoseconds: list[Decimal] = []
        if any(_NANOSECONDS.search(text) for text in texts):
            smallest = Decimal(10) ** (MIN_NANOSECOND_DIGITS - 1)
            nanoseconds = [value for value in values if _places(value) == 0 and value >= smallest]
        return cls(frozenset(exact), values, fractions, nanoseconds)

    def found(self, written: str, *, percent: bool = False) -> bool:
        """Число из отчёта (как написано) есть в материалах: такое же, округлённое до
        стольких знаков после запятой, сколько их в отчёте, или пересчитанное в 10³ и 10⁶
        раз в любую сторону, из наносекунд или — у процентов (percent) — из доли."""
        if normalize_number(written) in self.exact:
            return True
        if _DOTTED.fullmatch(written):
            return False
        value = _decimal(written)
        digits = significant_digits(written)
        if digits < MIN_ROUNDED_DIGITS:
            # Такое же значение, но записанное иначе: «0,00002» и «2e-05».
            return _any_between(self.values, value, value)
        # Округление до places знаков даёт value — значит, исходное число не дальше
        # половины последнего разряда. Ровно половина — тоже: 8,505 → 8,51 и 8,50.
        half = Decimal(5).scaleb(-_places(value) - 1)
        if _places(value) == 0 and digits < MIN_ROUNDED_INTEGER_DIGITS:
            # «14 сравнений» — счётчик: округлением из 13,72 мс он не получается.
            if self._near(value, value, percent):
                return True
            # «87 %» получается округлением доли 0,8731 — но не округлением 86,9 из
            # материалов: на замерах так проходила бы треть выдуманных процентов.
            return percent and _any_between(
                self.fractions,
                (value - half).scaleb(-PERCENT_POWER),
                (value + half).scaleb(-PERCENT_POWER),
            )
        return self._near(value - half, value + half, percent)

    def _near(self, low: Decimal, high: Decimal, percent: bool) -> bool:
        """Есть число материалов от low до high — как есть, пересчитанное в мс и мкс, из
        наносекунд или, если percent, из доли в проценты."""
        if _any_between(self.values, low, high):
            return True
        powers = (*UNIT_POWERS, PERCENT_POWER) if percent else UNIT_POWERS
        if any(
            _any_between(self.fractions, low.scaleb(-power), high.scaleb(-power))
            for power in powers
        ):
            return True
        return any(
            _any_between(self.nanoseconds, low.scaleb(power), high.scaleb(power))
            for power in NANOSECOND_POWERS
        )


def _split_columns(run: re.Match[str]) -> str:
    """Цифры через запятые — столбцы, если запятых больше одной («1000,1302,47550») или есть
    и точка («100,7234.3»). Одна запятая без точки («0,873») — дробная часть: иначе 873
    из точности 0,873 считалось бы числом из материалов."""
    text = run[0]
    return text.replace(",", " ") if text.count(",") > 1 or "." in text else text


def _counts(match: re.Match[str], separated: bool) -> bool:
    """Число из материала засчитывается. Запятые читаются как разделители — число с нулём
    впереди не отдельное: «0410» — дробная часть «0,0410». Запятые читаются как дробная
    часть — число с запятой, за которым сразу «.цифра» или «,цифра», склеено из соседних
    столбцов: «100,7234.3» — это 100 и 7234.3, а не 100,7234."""
    if separated:
        return _LEADING_ZERO.match(match[0]) is None
    return "," not in match[0] or _GLUED_TAIL.match(match.string, match.end()) is None


def significant_digits(written: str) -> int:
    """Значащие цифры числа, как оно написано: «0,0085» — 2, «8,50» — 3, «100» — 3."""
    return len("".join(char for char in written if char.isdigit()).lstrip("0"))


def _decimal(written: str) -> Decimal:
    """Значение числа с сохранением знаков после запятой: «0,0410» → 0.0410."""
    return Decimal(_GROUP_SEPARATOR.sub("", written).replace(",", "."))


def _places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)  # бесконечностей и NaN в тексте не бывает
    return max(0, -exponent)


def _any_between(values: list[Decimal], low: Decimal, high: Decimal) -> bool:
    return bisect_left(values, low) < bisect_right(values, high)


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
