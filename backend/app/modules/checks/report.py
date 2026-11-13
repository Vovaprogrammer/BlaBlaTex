"""Как проверки читают отчёт (docs/checks.md, «Как читается отчёт»).

Отчёт — главный файл и всё, что подключено из него через \\input и \\include, рекурсивно
и по порядку подключения. Файлы склеиваются в один текст — Report.source: «до» и «после»
считаются по позиции в нём, а не по номерам строк. Файл и строку позиции даёт locate.

Комментарии убраны так же, как в разборе лога сборки (uncomment), но внутри bbtcode,
lstlisting и verbatim код остаётся как есть. Report.plain — текст той же длины, где на
месте всего, что не станет словами в PDF (команды, пути, метки, ключи, необязательные
аргументы сразу после команды, код, преамбула), стоят пробелы. Позиции в нём те же, что
в source, поэтому место находки в plain — то же место в файле.

Это не полный разбор LaTeX: макросы не раскрываются, а аргументы ищутся по скобкам.
Его хватает для того, что пишет ИИ по правилам шаблона, и для обычного LaTeX студента.
"""

import re
import unicodedata
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from app.modules.builds.log_parser import uncomment
from app.modules.projects.paths import InvalidPathError, validate_path
from app.modules.templates.registry import META_FILE

ElementKind = Literal["figure", "table", "listing", "appendix", "formula"]
UseKind = Literal["image", "code"]
BareKind = Literal["image", "table", "code"]

# Окружения, внутри которых код, а не LaTeX: комментарии и команды в них не ищутся.
_CODE_ENVS = ("bbtcode", "lstlisting", "verbatim", "verbatim*")
_BEGIN_CODE = re.compile(r"\\begin\s*\{(bbtcode|lstlisting|verbatim\*?)\}")
_INCLUDE = re.compile(r"\\(?:input|include)\s*\{([^{}]*)\}")
# Команда (\имя и звёздочка), командный символ (\%, \\), $ или $$, а ещё { } ~ & —
# всё это не текст.
_TOKEN = re.compile(r"\\(?:([A-Za-z@]+)(\*?)|(.))|(\$\$?)|([{}~&])", re.S)
_BRACES = re.compile(r"\\.|[{}]", re.S)
_BRACKETS = re.compile(r"\\.|[{}\[\]]", re.S)
# Между аргументами TeX пропускает пробелы и один перевод строки.
_GAP = re.compile(r"[ \t]*\n?[ \t]*")
_WHITESPACE = re.compile(r"\s+")
# Дальше этого аргумент не ищется: незакрытая скобка не должна заставлять читать весь отчёт
# на каждой команде.
_MAX_ARGUMENT = 20_000

_FLOATS = {"figure", "figure*", "table", "table*", "longtable"}
_FIGURES = {"figure", "figure*"}
_TABLES = {"table", "table*"}
_TABULARS = {"tabular", "tabular*", "tabularx", "longtable"}
# Внутри них tabular — часть таблицы с подписью или другой таблицы, а не таблица без подписи.
_TABLE_HOLDERS = {"table", "table*", "bbttable", "figure", "figure*", *_TABULARS}
_LISTS = {"itemize", "enumerate"}
# Формулы с номером: у equation и multline номер один, у остальных — у каждой строки.
_ONE_NUMBER = {"equation", "multline"}
_ROW_NUMBERS = {"align", "gather", "eqnarray", "alignat", "flalign"}
_MATH_ENVS = {
    "equation", "multline", "align", "gather", "eqnarray", "alignat", "flalign",
    "displaymath", "math",
}  # fmt: skip
_SECTIONS = ("section", "subsection", "subsubsection")
_DEEP_HEADINGS = ("paragraph", "subparagraph")
# Командные символы, после которых в PDF остаётся сам символ: \% → %, \_ → _.
_ESCAPED_CHARS = set("%_&#${}")

# Обязательные аргументы, которые не текст: номера аргументов с 0. Необязательный аргумент
# сразу после команды текстом не считается никогда (правило 7).
_NOT_TEXT_ARGS: dict[str, tuple[int, ...]] = {
    "label": (0,),
    "ref": (0,),
    "eqref": (0,),
    "pageref": (0,),
    "autoref": (0,),
    "cite": (0,),
    "bibitem": (0,),
    "input": (0,),
    "include": (0,),
    "includegraphics": (0,),
    "lstinputlisting": (0,),
    "usepackage": (0,),
    "RequirePackage": (0,),
    "documentclass": (0,),
    "setlength": (0, 1),
    "addtolength": (0, 1),
    "setcounter": (0, 1),
    "addtocounter": (0, 1),
    "vspace": (0,),
    "hspace": (0,),
    "geometry": (0,),
    "newgeometry": (0,),
    "linespread": (0,),
    "fontsize": (0, 1),
    "setmainfont": (0,),
    "setsansfont": (0,),
    "setmonofont": (0,),
    "color": (0,),
    "textcolor": (0,),
    "pagecolor": (0,),
    "href": (0,),
    "graphicspath": (0,),
    "hypersetup": (0,),
    "lstset": (0,),
    "pagestyle": (0,),
    "thispagestyle": (0,),
    "rule": (0, 1),
    "resizebox": (0, 1),
    "scalebox": (0,),
    "multicolumn": (0, 1),
    "multirow": (0, 1),
    "cline": (0,),
    "newcommand": (0, 1),
    "renewcommand": (0, 1),
    "providecommand": (0, 1),
    "bbtScreenshot": (0, 2),
    "bbtCodeFile": (0, 2),
}
# Аргументы окружений после имени, которые не текст: (необязательный в начале, число
# обязательных).
_ENV_ARGS: dict[str, tuple[bool, int]] = {
    "tabular": (True, 1),
    "array": (True, 1),
    "tabular*": (False, 1),
    "tabularx": (False, 2),
    "longtable": (True, 1),
    "thebibliography": (False, 1),
    "minipage": (True, 1),
    "multicols": (False, 1),
    "wrapfigure": (True, 2),
    "alignat": (False, 1),
}


@dataclass(frozen=True)
class Span:
    """Кусок source: [start, end)."""

    start: int
    end: int


@dataclass(frozen=True)
class Element:
    """Рисунок, таблица, листинг, приложение или строка формулы с номером (правило 5)."""

    kind: ElementKind
    start: int
    end: int
    # Подпись или название приложения; None — подписи нет совсем (figure без \caption).
    caption: Span | None
    label: str | None
    label_at: int | None = None
    path: str | None = None
    # Текст листинга в source — у bbtcode и lstlisting.
    code: Span | None = None
    # Формула: есть ли у строки номер (без \nonumber и \notag).
    numbered: bool = True


@dataclass(frozen=True)
class FileUse:
    """Файл, вставленный в отчёт: картинка или код."""

    kind: UseKind
    path: str
    start: int


@dataclass(frozen=True)
class Bare:
    """Картинка, таблица или код без подписи и номера: \\includegraphics вне рисунка,
    tabular вне таблицы, verbatim."""

    kind: BareKind
    start: int
    path: str | None = None


@dataclass(frozen=True)
class Ref:
    kind: Literal["label", "cite"]
    key: str
    start: int


@dataclass(frozen=True)
class LabelDef:
    key: str
    start: int


@dataclass(frozen=True)
class BibItem:
    key: str
    start: int
    text: Span


@dataclass(frozen=True)
class Heading:
    name: str
    start: int
    title: Span


@dataclass(frozen=True)
class Item:
    """Пункт перечисления: текст — от \\item до следующего пункта или начала и конца
    списка; nested — сразу за пунктом начинается вложенный список."""

    start: int
    text: Span
    nested: bool


@dataclass(frozen=True)
class Env:
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class Command:
    name: str
    start: int
    end: int
    # Первый обязательный аргумент, если он есть: у \usepackage — имена пакетов.
    argument: Span | None


@dataclass(frozen=True)
class _Segment:
    start: int
    file: str
    offset: int


@dataclass(frozen=True)
class _Prepared:
    code: str
    spans: list[tuple[int, int]]
    line_starts: list[int]


@dataclass
class Report:
    """Отчёт, прочитанный по правилам docs/checks.md: текст и всё, что в нём нашлось."""

    source: str
    plain: str
    files: list[str]
    body: Span
    appendix: int | None
    code: list[Span]
    elements: list[Element]
    uses: list[FileUse]
    bare: list[Bare]
    refs: list[Ref]
    labels: list[LabelDef]
    bibitems: list[BibItem]
    headings: list[Heading]
    lists: list[list[Item]]
    envs: list[Env]
    math: list[Span]
    bibliography: list[Span]
    commands: list[Command]
    # Позиции сразу после \end{equation}, \end{equation*} и \]: там ищется «где».
    formula_ends: list[int]
    # Фигурные скобки и обратная косая черта в \_, \% и т. п.: в plain на их месте
    # пробелы, а show их убирает — «\texttt{main()}.» читается как «main().».
    escapes: list[int]
    _segments: list[_Segment]
    _starts: list[int]
    _files: dict[str, _Prepared]

    def locate(self, position: int) -> tuple[str, int]:
        """Файл и строка (с 1) позиции в source."""
        segment = self._segments[max(0, bisect_right(self._starts, position) - 1)]
        offset = segment.offset + position - segment.start
        return segment.file, bisect_right(self._files[segment.file].line_starts, offset)

    def show(self, span: Span) -> str:
        """Текст куска, как его прочтёт студент: без команд, пробелы подряд — один,
        «linear\\_search» — «linear_search»."""
        first = bisect_right(self.escapes, span.start - 1)
        last = bisect_right(self.escapes, span.end - 1)
        cursor = span.start
        pieces = []
        for escape in self.escapes[first:last]:
            pieces.append(self.plain[cursor:escape])
            cursor = escape + 1
        pieces.append(self.plain[cursor : span.end])
        return _WHITESPACE.sub(" ", "".join(pieces)).strip()

    def in_appendix(self, position: int) -> bool:
        return self.appendix is not None and position > self.appendix

    def file_code(self, path: str) -> str | None:
        """Файл отчёта без комментариев (код окружений — как есть) или None."""
        prepared = self._files.get(path)
        return prepared.code if prepared is not None else None


def read_report(main: str, texts: Mapping[str, str]) -> Report:
    """Отчёт с главным файлом main; texts — текстовые файлы проекта, путь → содержимое."""
    return _Reader(texts).read(main)


def strip_comments(text: str) -> str:
    """Файл без комментариев; внутри bbtcode, lstlisting и verbatim — код как есть."""
    return _prepare(text).code


def include_target(argument: str) -> str | None:
    """Путь файла из \\input{…}: от корня проекта, .tex дописывается; путь не по 9.8 — None."""
    name = unicodedata.normalize("NFC", argument.strip()).removeprefix("./")
    if not name.endswith(".tex"):
        name += ".tex"
    try:
        return validate_path(name)
    except InvalidPathError:
        return None


def argument_path(argument: str) -> str:
    """Путь из аргумента макроса, как его увидит сборка: без пробелов по краям, в NFC."""
    return unicodedata.normalize("NFC", argument.strip()).removeprefix("./")


def group(source: str, position: int) -> Span | None:
    """Аргумент в фигурных скобках, начиная с position (пробелы перед ним пропускаются):
    Span содержимого без скобок, или None, если аргумента нет или он не закрыт."""
    start = _GAP.match(source, position)
    position = start.end() if start else position
    if position >= len(source) or source[position] != "{":
        return None
    return _closing(source, position, _BRACES, "{", "}")


def optional(source: str, position: int) -> Span | None:
    """Необязательный аргумент [...] ровно с position: Span содержимого без скобок или None."""
    if position >= len(source) or source[position] != "[":
        return None
    return _closing(source, position, _BRACKETS, "[", "]")


def _closing(
    source: str, position: int, pattern: re.Pattern[str], opening: str, closing: str
) -> Span | None:
    depth = 0
    # Квадратные скобки внутри фигурных не считаются: [a={b]c}] — один аргумент.
    braces = 0
    limit = min(len(source), position + _MAX_ARGUMENT)
    for match in pattern.finditer(source, position, limit):
        token = match[0]
        if token.startswith("\\"):
            continue
        if opening == "[" and token in "{}":
            braces += 1 if token == "{" else -1
            continue
        if braces > 0:
            continue
        if token == opening:
            depth += 1
        elif token == closing:
            depth -= 1
            if depth == 0:
                return Span(position + 1, match.start())
    return None


def key_values(text: str) -> dict[str, tuple[int, int]]:
    """Ключи вида caption=…, label=… из необязательного аргумента: ключ → (начало, конец)
    значения в text, без фигурных скобок вокруг значения."""
    result: dict[str, tuple[int, int]] = {}
    depth = 0
    start = 0
    parts: list[tuple[int, int]] = []
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append((start, index))
            start = index + 1
    parts.append((start, len(text)))
    for first, last in parts:
        piece = text[first:last]
        if "=" not in piece:
            continue
        name, _, value = piece.partition("=")
        position = first + len(name) + 1
        stripped = value.strip()
        lead = len(value) - len(value.lstrip())
        begin, end = position + lead, position + lead + len(stripped)
        if stripped.startswith("{") and stripped.endswith("}"):
            begin, end = begin + 1, end - 1
        result[name.strip()] = (begin, end)
    return result


def _prepare(text: str) -> _Prepared:
    """Файл без комментариев, с кусками кода окружений; строк столько же, сколько в text."""
    pieces: list[str] = []
    spans: list[tuple[int, int]] = []
    offset = 0
    env: str | None = None
    code_start = 0
    lines = text.split("\n")
    for index, line in enumerate(lines):
        newline = "\n" if index < len(lines) - 1 else ""
        if env is not None:
            close = line.find(f"\\end{{{env}}}")
            if close == -1:
                pieces.append(line + newline)
                offset += len(line) + len(newline)
                continue
            spans.append((code_start, offset + close))
            pieces.append(line[:close])
            offset += close
            line = line[close:]
            env = None
        clean = uncomment(line)
        match = _BEGIN_CODE.search(clean)
        if match is not None:
            close = clean.find(f"\\end{{{match[1]}}}", match.end())
            if close != -1:
                # Окружение целиком в одной строке.
                spans.append((offset + match.end(), offset + close))
            else:
                env = match[1]
                code_start = offset + len(clean) + len(newline)
        pieces.append(clean + newline)
        offset += len(clean) + len(newline)
    if env is not None:
        spans.append((code_start, offset))
    code = "".join(pieces)
    line_starts = [0, *(match.end() for match in re.finditer("\n", code))]
    return _Prepared(code, spans, line_starts)


@dataclass
class _Open:
    """Окружение, которое ещё не закрылось, и то, что нашлось внутри."""

    name: str
    start: int
    head_end: int
    caption: Span | None = None
    label: LabelDef | None = None
    labels: list[LabelDef] = field(default_factory=list)
    rows: list[Span] = field(default_factory=list)
    nonumber: list[int] = field(default_factory=list)
    code: Span | None = None
    options: dict[str, Span] = field(default_factory=dict)
    arguments: list[Span] = field(default_factory=list)
    bare: bool = False


class _Reader:
    def __init__(self, texts: Mapping[str, str]) -> None:
        self.texts = texts
        self.files: dict[str, _Prepared] = {}
        self.order: list[str] = []
        self.pieces: list[str] = []
        self.segments: list[_Segment] = []
        self.code: list[Span] = []
        self.length = 0

    def read(self, main: str) -> Report:
        if main in self.texts:
            self._visit(main, (main,))
        source = "".join(self.pieces)
        if not self.segments:
            self.segments.append(_Segment(0, main, 0))
            self.files.setdefault(main, _prepare(""))
        return _Scanner(source, self.code).scan(self, main)

    def _visit(self, path: str, stack: tuple[str, ...]) -> None:
        prepared = self.files.get(path)
        if prepared is None:
            prepared = self.files[path] = _prepare(self.texts[path])
        if path not in self.order:
            self.order.append(path)
        cursor = 0
        for match in _INCLUDE.finditer(prepared.code):
            if _inside(prepared.spans, match.start()):
                continue
            target = include_target(match[1])
            # meta.tex как текст не проверяется: по нему смотрит только title-empty.
            if target is None or target == META_FILE or target not in self.texts:
                continue
            if target in stack:
                continue
            self._emit(path, prepared, cursor, match.end())
            self._visit(target, (*stack, target))
            cursor = match.end()
        self._emit(path, prepared, cursor, len(prepared.code))

    def _emit(self, path: str, prepared: _Prepared, start: int, end: int) -> None:
        if start >= end:
            return
        self.segments.append(_Segment(self.length, path, start))
        for first, last in prepared.spans:
            if first < end and last > start:
                self.code.append(
                    Span(
                        self.length + max(first, start) - start,
                        self.length + min(last, end) - start,
                    )
                )
        self.pieces.append(prepared.code[start:end])
        self.length += end - start


def _inside(spans: list[tuple[int, int]], position: int) -> bool:
    return any(first <= position < last for first, last in spans)


class _Scanner:
    """Один проход по source: команды, окружения, аргументы и то, что не текст."""

    def __init__(self, source: str, code: list[Span]) -> None:
        self.source = source
        self.code_spans = sorted(code, key=lambda span: span.start)
        self.code_starts = [span.start for span in self.code_spans]
        self.hidden: list[tuple[int, int]] = [(span.start, span.end) for span in self.code_spans]
        self.stack: list[_Open] = []
        self.elements: list[Element] = []
        self.uses: list[FileUse] = []
        self.bare: list[Bare] = []
        self.refs: list[Ref] = []
        self.labels: list[LabelDef] = []
        self.bibitems: list[tuple[str, int, int]] = []
        self.headings: list[Heading] = []
        self.envs: list[Env] = []
        self.list_envs: list[tuple[int, int, bool]] = []
        self.items: list[tuple[int, int]] = []
        self.math: list[Span] = []
        self.bibliography: list[Span] = []
        self.commands: list[Command] = []
        self.formula_ends: list[int] = []
        self.escapes: list[int] = []
        self.body_start = 0
        self.body_end: int | None = None
        self.appendix: int | None = None
        self.math_open: tuple[str, int] | None = None

    def scan(self, reader: _Reader, main: str) -> Report:
        source = self.source
        position = 0
        code_index = 0
        while (match := _TOKEN.search(source, position)) is not None:
            start = match.start()
            # Внутри кода окружений команд нет.
            while code_index < len(self.code_spans) and self.code_spans[code_index].end <= start:
                code_index += 1
            if code_index < len(self.code_spans) and self.code_spans[code_index].start <= start:
                position = self.code_spans[code_index].end
                continue
            position = self._token(match)
        body = Span(self.body_start, self.body_end if self.body_end is not None else len(source))
        self.hide(0, body.start)
        self.hide(body.end, len(source))
        return Report(
            source=source,
            plain=self._plain(),
            files=reader.order or [main],
            body=body,
            appendix=self.appendix,
            code=self.code_spans,
            elements=sorted(self.elements, key=lambda element: element.start),
            uses=self.uses,
            bare=self.bare,
            refs=self.refs,
            labels=self.labels,
            bibitems=self._bibitems(),
            headings=self.headings,
            lists=self._lists(),
            envs=self.envs,
            math=self.math,
            bibliography=self.bibliography,
            commands=self.commands,
            formula_ends=self.formula_ends,
            escapes=self.escapes,
            _segments=reader.segments,
            _starts=[segment.start for segment in reader.segments],
            _files=reader.files,
        )

    def hide(self, start: int, end: int) -> None:
        if start < end:
            self.hidden.append((start, end))

    def _plain(self) -> str:
        pieces: list[str] = []
        cursor = 0
        for start, end in sorted(self.hidden):
            if end <= cursor:
                continue
            start = max(start, cursor)
            pieces.append(self.source[cursor:start])
            pieces.append(" " * (end - start))
            cursor = end
        pieces.append(self.source[cursor:])
        return "".join(pieces)

    def _token(self, match: re.Match[str]) -> int:
        start, end = match.span()
        name, star, symbol, dollars, special = match.groups()
        self.hide(start, end)
        if special is not None:
            if special in "{}":
                self.escapes.append(start)
            return end
        if dollars is not None:
            self._dollar(dollars, start, end)
            return end
        if symbol is not None:
            return self._symbol(symbol, start, end)
        return self._command(name, star, start, end)

    def _dollar(self, dollars: str, start: int, end: int) -> None:
        if self.math_open is None:
            self.math_open = (dollars, start)
        elif self.math_open[0] == dollars:
            self.math.append(Span(self.math_open[1], end))
            self.math_open = None

    def _symbol(self, symbol: str, start: int, end: int) -> int:
        if symbol in _ESCAPED_CHARS:
            # \% → % в PDF: прячется только обратная косая черта.
            self.hidden[-1] = (start, start + 1)
            self.escapes.append(start)
        elif symbol in "[(":
            self.math_open = (symbol, start)
        elif symbol in "])":
            if self.math_open is not None and self.math_open[0] == {"]": "[", ")": "("}[symbol]:
                self.math.append(Span(self.math_open[1], end))
            self.math_open = None
            if symbol == "]":
                self.formula_ends.append(end)
        elif symbol == "\\" and self.stack:
            self.stack[-1].rows.append(Span(start, end))
        return end

    def _command(self, name: str, star: str, start: int, end: int) -> int:
        source = self.source
        if name in ("verb", "lstinline") and end < len(source):
            return self._inline_code(name, start, end)
        first_optional = optional(source, end)
        after = end
        if first_optional is not None:
            # У \lstinputlisting в необязательном аргументе подпись — её прячет обработчик.
            if name != "lstinputlisting":
                self.hide(first_optional.start - 1, first_optional.end + 1)
            after = first_optional.end + 1
        if name == "begin":
            return self._begin(start, after)
        if name == "end":
            return self._end(start, after)
        argument = group(source, after)
        self.commands.append(Command(name, start, end, argument))
        masked = _NOT_TEXT_ARGS.get(name, ())
        handler = _HANDLED.get(name)
        count = max(1 + max(masked, default=-1), handler[0] if handler else 0)
        arguments = self._arguments(after, count) if count else []
        for index in masked:
            if index < len(arguments):
                self.hide(arguments[index].start - 1, arguments[index].end + 1)
        if handler is not None:
            handler[1](self, name, start, star == "*", first_optional, arguments)
        return end

    def _arguments(self, position: int, count: int) -> list[Span]:
        arguments: list[Span] = []
        for _ in range(count):
            argument = group(self.source, position)
            if argument is None:
                break
            arguments.append(argument)
            position = argument.end + 1
        return arguments

    def _inline_code(self, name: str, start: int, end: int) -> int:
        """\\verb|код|, \\lstinline|код|, \\lstinline[ключи]{код}: код в строке — не текст."""
        position = end
        if name == "lstinline":
            options = optional(self.source, position)
            if options is not None:
                position = options.end + 1
        if position >= len(self.source):
            return end
        delimiter = self.source[position]
        closing = "}" if name == "lstinline" and delimiter == "{" else delimiter
        close = self.source.find(closing, position + 1)
        newline = self.source.find("\n", position + 1)
        if close == -1 or (newline != -1 and newline < close):
            return end
        self.hide(start, close + 1)
        return close + 1

    def _begin(self, start: int, position: int) -> int:
        name_span = group(self.source, position)
        if name_span is None:
            return position
        self.hide(name_span.start - 1, name_span.end + 1)
        name = self.source[name_span.start : name_span.end].strip()
        head = name_span.end + 1
        env = _Open(name, start, head)
        holders = {open_env.name for open_env in self.stack}
        if name == "document":
            self.body_start = head
        if name in _TABULARS and not holders & _TABLE_HOLDERS:
            env.bare = True
        if name in ("bbtcode", "bbttable"):
            env.arguments = self._arguments(head, 3 if name == "bbtcode" else 2)
            hidden = (0, 2) if name == "bbtcode" else (1,)
            for index in hidden:
                if index < len(env.arguments):
                    argument = env.arguments[index]
                    self.hide(argument.start - 1, argument.end + 1)
            if env.arguments:
                head = env.arguments[-1].end + 1
        elif name == "lstlisting":
            options = optional(self.source, head)
            if options is not None:
                self._options(env, options)
                head = options.end + 1
        else:
            has_optional, count = _ENV_ARGS.get(name, (True, 0))
            if has_optional:
                options = optional(self.source, head)
                if options is not None:
                    self.hide(options.start - 1, options.end + 1)
                    head = options.end + 1
            for argument in self._arguments(head, count):
                self.hide(argument.start - 1, argument.end + 1)
                head = argument.end + 1
        env.head_end = head
        if name in _CODE_ENVS:
            env.code = self._code_after(head)
        if name in _LISTS:
            nested = any(open_env.name in _LISTS for open_env in self.stack)
            self.list_envs.append((start, -1, nested))
        self.stack.append(env)
        # Аргументы окружения проход читает дальше сам: в подписи бывают \ref и скобки.
        return name_span.end + 1

    def _code_after(self, position: int) -> Span | None:
        index = bisect_left(self.code_starts, position)
        return self.code_spans[index] if index < len(self.code_spans) else None

    def _options(self, env: _Open, options: Span) -> None:
        """Ключи lstlisting и \\lstinputlisting: подпись — текст, остальное — нет."""
        text = self.source[options.start : options.end]
        values = key_values(text)
        caption = values.get("caption")
        if caption is None:
            self.hide(options.start - 1, options.end + 1)
        else:
            self.hide(options.start - 1, options.start + caption[0])
            self.hide(options.start + caption[1], options.end + 1)
        env.options = {
            key: Span(options.start + first, options.start + last)
            for key, (first, last) in values.items()
        }

    def _end(self, start: int, position: int) -> int:
        name_span = group(self.source, position)
        if name_span is None:
            return position
        end = name_span.end + 1
        self.hide(name_span.start - 1, end)
        name = self.source[name_span.start : name_span.end].strip()
        if name == "document":
            self.body_end = start
            return end
        index = next(
            (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i].name == name), None
        )
        if index is None:
            return end
        env = self.stack[index]
        del self.stack[index:]
        self.envs.append(Env(name, env.start, end))
        self._close(env, start, end)
        return end

    def _close(self, env: _Open, end_start: int, end: int) -> None:
        name = env.name
        base = name.removesuffix("*")
        if base in _MATH_ENVS:
            self.math.append(Span(env.start, end))
        if name in ("equation", "equation*"):
            self.formula_ends.append(end)
        if name in _LISTS:
            for i in range(len(self.list_envs) - 1, -1, -1):
                if self.list_envs[i][0] == env.start:
                    self.list_envs[i] = (env.start, end_start, self.list_envs[i][2])
                    break
        if name == "thebibliography":
            self.bibliography.append(Span(env.start, end_start))
        if name in _FIGURES or name in _TABLES:
            kind: ElementKind = "figure" if name in _FIGURES else "table"
            self._element(kind, env, end)
        elif name == "longtable":
            if env.caption is not None:
                self._element("table", env, end)
            elif env.bare:
                self.bare.append(Bare("table", env.start))
        elif env.bare:
            self.bare.append(Bare("table", env.start))
        elif name == "bbttable":
            self._macro_element("table", env.start, end, env.arguments, caption=0, label=1)
        elif name == "bbtcode":
            self._macro_element(
                "listing", env.start, end, env.arguments, caption=1, label=2, code=env.code
            )
        elif name == "lstlisting":
            self._listing_from_options(env.start, end, env.options, code=env.code)
        elif name in ("verbatim", "verbatim*"):
            self.bare.append(Bare("code", env.start))
        elif name in _ONE_NUMBER or name in _ROW_NUMBERS:
            self._formulas(env, end_start, end)

    def _element(self, kind: ElementKind, env: _Open, end: int) -> None:
        label = env.label
        self.elements.append(
            Element(
                kind,
                env.start,
                end,
                env.caption,
                label.key if label else None,
                label.start if label else None,
            )
        )

    def _macro_element(
        self,
        kind: ElementKind,
        start: int,
        end: int,
        arguments: list[Span],
        *,
        caption: int,
        label: int,
        path: int | None = None,
        code: Span | None = None,
    ) -> None:
        caption_span = arguments[caption] if caption < len(arguments) else None
        key = None
        key_at = None
        if label < len(arguments):
            key = self.source[arguments[label].start : arguments[label].end].strip() or None
            key_at = arguments[label].start
            if key is not None:
                self.labels.append(LabelDef(key, key_at))
        file = None
        if path is not None and path < len(arguments):
            file = argument_path(self.source[arguments[path].start : arguments[path].end])
        self.elements.append(Element(kind, start, end, caption_span, key, key_at, file, code))

    def _listing_from_options(
        self,
        start: int,
        end: int,
        options: dict[str, Span],
        *,
        code: Span | None = None,
        path: str | None = None,
    ) -> None:
        caption = options.get("caption")
        label_span = options.get("label")
        key = None
        if label_span is not None:
            key = self.source[label_span.start : label_span.end].strip() or None
            if key is not None:
                self.labels.append(LabelDef(key, label_span.start))
        self.elements.append(
            Element(
                "listing",
                start,
                end,
                caption,
                key,
                label_span.start if label_span else None,
                path,
                code,
            )
        )

    def _formulas(self, env: _Open, end_start: int, end: int) -> None:
        if env.name.endswith("*"):
            return
        rows: list[Span] = []
        if env.name in _ONE_NUMBER:
            rows = [Span(env.start, end_start)]
        else:
            cursor = env.start
            for separator in env.rows:
                rows.append(Span(cursor, separator.start))
                cursor = separator.end
            rows.append(Span(cursor, end_start))
        for index, row in enumerate(rows):
            if index > 0 and not self.source[max(row.start, env.head_end) : row.end].strip():
                continue
            numbered = not any(row.start <= mark < row.end for mark in env.nonumber)
            label = next((item for item in env.labels if row.start <= item.start < row.end), None)
            begin = env.start if index == 0 else _skip_space(self.source, row.start)
            self.elements.append(
                Element(
                    "formula",
                    begin,
                    row.end if index < len(rows) - 1 else end,
                    None,
                    label.key if label else None,
                    label.start if label else None,
                    numbered=numbered,
                )
            )

    def _innermost(self, names: set[str]) -> _Open | None:
        for env in reversed(self.stack):
            if env.name in names:
                return env
        return None

    def _bibitems(self) -> list[BibItem]:
        items: list[BibItem] = []
        for index, (key, start, text_start) in enumerate(self.bibitems):
            limit = next(
                (span.end for span in self.bibliography if span.start <= start < span.end),
                len(self.source),
            )
            following = self.bibitems[index + 1][1] if index + 1 < len(self.bibitems) else limit
            items.append(BibItem(key, start, Span(text_start, min(following, limit))))
        return items

    def _lists(self) -> list[list[Item]]:
        boundaries: list[tuple[int, bool]] = sorted(
            [(start, False) for start, _ in self.items]
            + [(start, True) for start, _, _ in self.list_envs]
            + [(end, False) for _, end, _ in self.list_envs if end >= 0]
        )
        positions = [position for position, _ in boundaries]
        result: list[list[Item]] = []
        for start, end, nested in self.list_envs:
            if nested:
                continue
            limit = end if end >= 0 else len(self.source)
            entries: list[Item] = []
            for item_start, text_start in self.items:
                if not start < item_start < limit:
                    continue
                index = bisect_right(positions, text_start)
                text_end, opens_list = (
                    boundaries[index] if index < len(boundaries) else (limit, False)
                )
                entries.append(Item(item_start, Span(text_start, text_end), opens_list))
            result.append(entries)
        return result


def _skip_space(source: str, position: int) -> int:
    while position < len(source) and source[position].isspace():
        position += 1
    return position


# Обработчик команды: сканер, имя, начало, есть ли звёздочка, необязательный аргумент
# и обязательные аргументы.
type _Handler = Callable[[_Scanner, str, int, bool, Span | None, list[Span]], None]


def _screenshot(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    end = args[-1].end + 1 if args else start
    scanner._macro_element("figure", start, end, args, caption=1, label=2, path=0)
    if args:
        path = argument_path(scanner.source[args[0].start : args[0].end])
        scanner.uses.append(FileUse("image", path, start))


def _code_file(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    end = args[-1].end + 1 if args else start
    scanner._macro_element("listing", start, end, args, caption=1, label=2, path=0)
    if args:
        path = argument_path(scanner.source[args[0].start : args[0].end])
        scanner.uses.append(FileUse("code", path, start))


def _includegraphics(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if not args:
        return
    path = argument_path(scanner.source[args[0].start : args[0].end])
    scanner.uses.append(FileUse("image", path, start))
    if scanner._innermost(_FIGURES) is None:
        scanner.bare.append(Bare("image", start, path))


def _inputlisting(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if not args:
        return
    path = argument_path(scanner.source[args[0].start : args[0].end])
    scanner.uses.append(FileUse("code", path, start))
    env = _Open("lstinputlisting", start, start)
    if opt is not None:
        scanner._options(env, opt)
    scanner._listing_from_options(start, args[0].end + 1, env.options, path=path)


def _caption(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    env = scanner._innermost(_FLOATS)
    if env is not None and env.caption is None and args:
        env.caption = args[0]


def _label(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if not args:
        return
    key = scanner.source[args[0].start : args[0].end].strip()
    if not key:
        return
    label = LabelDef(key, start)
    scanner.labels.append(label)
    env = scanner._innermost(_FLOATS | _ONE_NUMBER | _ROW_NUMBERS)
    if env is not None:
        env.labels.append(label)
        if env.label is None:
            env.label = label


def _ref(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if args:
        key = scanner.source[args[0].start : args[0].end].strip()
        scanner.refs.append(Ref("label", key, start))


def _cite(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if not args:
        return
    text = scanner.source[args[0].start : args[0].end]
    offset = args[0].start
    for piece in text.split(","):
        key = piece.strip()
        if key:
            scanner.refs.append(Ref("cite", key, offset + piece.find(key)))
        offset += len(piece) + 1


def _bibitem(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if args:
        key = scanner.source[args[0].start : args[0].end].strip()
        scanner.bibitems.append((key, start, args[0].end + 1))


def _heading(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if not args:
        return
    scanner.headings.append(Heading(name, start, args[0]))
    if name != "section" or star or scanner.appendix is None:
        return
    # Приложение: \section после \appendix, метка — \label сразу после заголовка.
    after = _skip_space(scanner.source, args[0].end + 1)
    key = None
    key_at = None
    if scanner.source.startswith("\\label", after):
        label = group(scanner.source, after + len("\\label"))
        if label is not None:
            key = scanner.source[label.start : label.end].strip() or None
            key_at = after
    scanner.elements.append(Element("appendix", start, args[0].end + 1, args[0], key, key_at))


def _appendix(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if scanner.appendix is None and start >= scanner.body_start:
        scanner.appendix = start


def _item(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    if scanner._innermost(_LISTS) is None:
        return
    text_start = opt.end + 1 if opt is not None else start + len("\\item")
    scanner.items.append((start, text_start))


def _nonumber(
    scanner: _Scanner, name: str, start: int, star: bool, opt: Span | None, args: list[Span]
) -> None:
    env = scanner._innermost(_ONE_NUMBER | _ROW_NUMBERS)
    if env is not None:
        env.nonumber.append(start)


# Команда → (сколько обязательных аргументов прочитать, обработчик).
_HANDLED: dict[str, tuple[int, _Handler]] = {
    "bbtScreenshot": (3, _screenshot),
    "bbtCodeFile": (3, _code_file),
    "includegraphics": (1, _includegraphics),
    "lstinputlisting": (1, _inputlisting),
    "caption": (1, _caption),
    "label": (1, _label),
    "ref": (1, _ref),
    "eqref": (1, _ref),
    "pageref": (1, _ref),
    "cite": (1, _cite),
    "bibitem": (1, _bibitem),
    "appendix": (0, _appendix),
    "item": (0, _item),
    "nonumber": (0, _nonumber),
    "notag": (0, _nonumber),
    **{name: (1, _heading) for name in (*_SECTIONS, *_DEEP_HEADINGS)},
}
