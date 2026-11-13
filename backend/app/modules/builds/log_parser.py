"""Разбор лога TeX в ошибки и предупреждения с файлом, строкой и контекстом (9.4).

Компилятор запускает TeX с -file-line-error, поэтому большинство ошибок выглядят так:

    ./sections/intro.tex:12: Undefined control sequence.
    l.12 \\textbff

Часть ошибок (например, «File `x.sty' not found») TeX пишет по-старому, с «! » в начале;
строка тогда — в «l.N» ниже, а файл — тот, что сейчас открыт. Открытые файлы видны
по скобкам в логе: «(./sections/intro.tex» … «)».

Незакрытое окружение LaTeX замечает там, где его закрыл чужой \\end, — обычно
\\end{document} в main.tex: «\\begin{itemize} on input line 3 ended by \\end{document}».
В каком файле была «input line 3», лог не пишет; её ищем среди файлов, которые уже
закрылись (_environment_start).

Заодно тот же проход собирает то, что нужно проверкам по PDF (docs/checks.md): текст
за правым полем («Overfull \\hbox … in paragraph at lines 3--11») и символы, которых нет
в шрифте («Missing character: There is no ✅ …»), — с файлом, открытым в этот момент.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.modules.builds.schemas import BuildError
from app.modules.projects.schemas import Engine

Severity = Literal["error", "warning"]

# TeX переносит строки лога, длиннее 79 символов (max_print_line в TeX Live).
MAX_PRINT_LINE = 79
# Сколько строк исходника показывать до и после места ошибки (9.4).
CONTEXT_LINES = 10
# Не больше стольких записей на сборку: ошибки идут первыми, потом предупреждения.
MAX_ENTRIES = 50
# Не больше стольких переполненных боксов и пропавших символов: в логе зациклившегося
# документа их бывают тысячи, а проверкам хватит первых.
MAX_BOX_ENTRIES = 1000
# Лог зациклившегося документа бывает десятки МБ; ошибки ищем в его начале.
MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_MESSAGE_CHARS = 500
MAX_CONTEXT_LINE_CHARS = 200
# Насколько далеко после «! …» искать «l.N» и «файл:строка: Emergency stop.».
_LOOKAHEAD_LINES = 20
# Предупреждение пакета продолжается строками с «(имя пакета)» в начале.
_MAX_WARNING_LINES = 6

_FILE_LINE = re.compile(r"^(?P<file>[^:]+?):(?P<line>\d+): (?P<message>.*)$")
_BANG = re.compile(r"^! (?P<message>.*)$")
_LINE_REF = re.compile(r"^l\.(?P<line>\d+)(?: (?P<text>.*))?$")
_WARNING = re.compile(r"^(?:LaTeX|Package \S+|Class \S+) Warning: (?P<message>.*)$")
_CONTINUATION = re.compile(r"^\([^()\s]+\)\s+(?P<text>.*)$")
_INPUT_LINE = re.compile(r"\s*on input line (?P<line>\d+)\.?$")
_PAGES = re.compile(r"^Output written on .+ \((?P<pages>\d+) pages?\b")
_PARENS = re.compile(r"[()]")
_UNTIL_PAREN = re.compile(r"[^()]*")
# Строки с текстом документа, а не лога. Скобки в них — из текста студента, файлы по ним
# не отслеживаются. Это контекст ошибки «l.12 …» и «<argument> …» (за ним — вторая
# половина той же строки, с отступом), строка после «Runaway argument?» и содержимое
# переполненного бокса (до пустой строки).
_CONTEXT_DISPLAY = re.compile(r"^(?:l\.\d+|<[^>]*>)(?: |$)")
_RUNAWAY = re.compile(r"^Runaway \w+\?$")
_BOX_DISPLAY = re.compile(r"^(?:Over|Under)full \\[hv]box")
# Строка шире поля: «Overfull \hbox (345.91956pt too wide) in paragraph at lines 3--11»;
# у таблицы — «in alignment at lines 11--11».
_OVERFULL = re.compile(
    r"^Overfull \\hbox \((?P<points>\d+(?:\.\d+)?)pt too wide\) "
    r"in (?P<kind>paragraph|alignment) at lines (?P<first>\d+)--(?P<last>\d+)"
)
# Символа нет в шрифте (класс включает \tracinglostchars=2): «Missing character: There is
# no ✅ (U+2705) in font Liberation Mono/OT:script=latn;language=dflt;!».
_MISSING_CHAR = re.compile(r"^Missing character: There is no (?P<char>.+?) \(U\+[0-9A-Fa-f]+\)")
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
# Неизвестная команда — последняя на верхней строке контекста: «l.8 \textbff».
_LAST_COMMAND = re.compile(r"(\\[A-Za-z@]+|\\.)\s*$")
_EMERGENCY_STOP = "Emergency stop."
_LATEX_ERROR_PREFIX = "LaTeX Error: "
# Ошибку погасили намеренно (\ignoreprimitiveerror), но TeX всё равно пишет её в лог:
# «./main.tex:79: ignored error: Infinite glue shrinkage found in box being split».
# Так ядро LaTeX выводит страницу с длинной таблицей longtable. PDF при этом правильный.
_IGNORED_ERROR_PREFIX = "ignored error: "
# Окружение закрыл не свой \end: «\begin{itemize} on input line 3 ended by \end{document}.»
_ENDED_BY = re.compile(r"^\\begin\{(?P<env>[^{}]+)\} on input line (?P<line>\d+) ended by \\end\{")
# Комментарий TeX: от «%» до конца строки, если перед «%» чётное число «\» (ноль — тоже):
# «\%» — знак процента, а «\\%» — перевод строки и комментарий.
_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*")


@dataclass(frozen=True)
class Overfull:
    """Строка шире поля: абзац (paragraph) или таблица (alignment) на строках first–last."""

    file: str | None
    first: int
    last: int
    kind: Literal["paragraph", "alignment"]
    points: float


@dataclass(frozen=True)
class MissingChar:
    """Символа char нет в шрифте; file — файл проекта, открытый в этот момент, или None."""

    file: str | None
    char: str


@dataclass(frozen=True)
class ParsedLog:
    errors: list[BuildError]
    pages: int | None
    overfull: list[Overfull] = field(default_factory=list)
    missing_chars: list[MissingChar] = field(default_factory=list)


@dataclass
class _Parser:
    # Пути текстовых файлов проекта → содержимое: для файлов в логе и контекста.
    sources: dict[str, str]
    lines: list[str]

    def __post_init__(self) -> None:
        # Стек открытых файлов: путь в проекте или None (системный файл, просто скобка).
        self.stack: list[str | None] = []
        # Файлы проекта, которые TeX уже дочитал, — по порядку, без повторов.
        self.closed: list[str] = []
        # Строки файлов и файлы без комментариев: ошибок по одному файлу бывает много.
        self.lines_cache: dict[str, list[str]] = {}
        self.code_cache: dict[str, str] = {}
        self.entries: list[BuildError] = []
        self.seen: set[tuple[str | None, int | None, str, Severity]] = set()
        self.counts: dict[Severity, int] = {"error": 0, "warning": 0}
        self.pages: int | None = None
        self.overfull: list[Overfull] = []
        self.missing_chars: list[MissingChar] = []

    def parse(self) -> ParsedLog:
        # Что из следующих строк — текст документа: вторая половина контекста (если она
        # с отступом), строка после «Runaway …?» или всё до пустой строки.
        context_tail, next_line, until_blank = False, False, False
        for index, line in enumerate(self.lines):
            is_tail = context_tail and (not line or line.startswith(" "))
            if is_tail or next_line or (until_blank and line.strip()):
                context_tail = next_line = False
                continue
            context_tail = until_blank = False
            if match := _FILE_LINE.match(line):
                self._file_line_error(index, match)
            elif match := _BANG.match(line):
                self._bang_error(index, match["message"])
            elif match := _WARNING.match(line):
                self._warning(index, match["message"])
            elif match := _PAGES.match(line):
                self.pages = int(match["pages"])
            elif match := _MISSING_CHAR.match(line):
                if len(self.missing_chars) < MAX_BOX_ENTRIES:
                    self.missing_chars.append(MissingChar(self._current_file(), match["char"]))
            elif _CONTEXT_DISPLAY.match(line):
                context_tail = True
            elif _RUNAWAY.match(line):
                next_line = True
            elif _BOX_DISPLAY.match(line):
                self._overfull(line)
                until_blank = True
            else:
                self._track_files(line)
        return ParsedLog(_limit(self.entries), self.pages, self.overfull, self.missing_chars)

    def _overfull(self, line: str) -> None:
        match = _OVERFULL.match(line)
        if match is None or len(self.overfull) >= MAX_BOX_ENTRIES:
            return
        kind: Literal["paragraph", "alignment"] = (
            "alignment" if match["kind"] == "alignment" else "paragraph"
        )
        self.overfull.append(
            Overfull(
                file=self._current_file(),
                first=int(match["first"]),
                last=int(match["last"]),
                kind=kind,
                points=float(match["points"]),
            )
        )

    def _file_line_error(self, index: int, match: re.Match[str]) -> None:
        file = self._project_path(match["file"])
        # «a:1: b» бывает и в обычном тексте лога; путь — только ./…, /… или файл проекта.
        if file is None and not match["file"].startswith(("./", "/")):
            return
        # Ошибка в чужом файле (например, в классе шаблона): номер строки пользователю
        # ничего не скажет — остаётся только текст.
        self._error(index, match["message"], file, int(match["line"]) if file else None)

    def _bang_error(self, index: int, message: str) -> None:
        file, line = self._current_file(), None
        for following in self.lines[index + 1 : index + 1 + _LOOKAHEAD_LINES]:
            if _BANG.match(following):
                break
            if match := _FILE_LINE.match(following):
                file = self._project_path(match["file"])
                line = int(match["line"]) if file else None
                break
            if match := _LINE_REF.match(following):
                line = int(match["line"])
                break
        self._error(index, message, file, line)

    def _error(self, index: int, message: str, file: str | None, line: int | None) -> None:
        message = message.removeprefix(_LATEX_ERROR_PREFIX)
        # «Emergency stop» — следствие предыдущей ошибки, а не новая.
        if message == _EMERGENCY_STOP and self.counts["error"] > 0:
            return
        # Погашенная ошибка — не ошибка: исправлять студенту нечего.
        if message.startswith(_IGNORED_ERROR_PREFIX):
            return
        if message.startswith("Undefined control sequence"):
            command = self._undefined_command(index)
            if command is not None:
                message = f"Undefined control sequence: {command}"
        # Ошибок уже столько, что эта не попадёт в список, — и искать её место незачем.
        if (match := _ENDED_BY.match(message)) and self.counts["error"] < MAX_ENTRIES:
            file, line = self._environment_start(match["env"], int(match["line"]), file, line)
        self._add(message, file, line, "error")

    def _environment_start(
        self, env: str, start: int, file: str | None, line: int | None
    ) -> tuple[str | None, int | None]:
        """Где начато окружение, которое закрыл чужой \\end, — или file и line, где LaTeX
        это заметил, если файл не определить.

        Начато в файле, который ещё открыт (main.tex, или лишний \\end в разделе закрыл
        окружение из main.tex), — правильное место и есть то, где LaTeX это заметил.
        Иначе окружение осталось незакрытым в файле, который уже дочитан: ищем такой,
        где на строке start стоит его \\begin. Таких два — берём тот, где \\begin этого
        окружения больше, чем \\end. Лучше ссылка туда, где LaTeX заметил ошибку (строка
        начала есть в её тексте), чем уверенная ссылка не в тот файл.
        """
        begin, end = f"\\begin{{{env}}}", f"\\end{{{env}}}"
        opened = {path for path in self.stack if path is not None}
        if any(begin in self._code_line(path, start) for path in opened):
            return file, line
        candidates = [
            path
            for path in self.closed
            if path not in opened and begin in self._code_line(path, start)
        ]
        if len(candidates) > 1:
            candidates = [
                path
                for path in candidates
                if (code := self._code(path)).count(begin) > code.count(end)
            ]
        if len(candidates) == 1:
            return candidates[0], start
        return file, line

    def _source_lines(self, path: str) -> list[str]:
        """Строки файла проекта — как их считает TeX: только по \\n, \\r\\n и \\r.
        splitlines делил бы ещё и по \\f, \\v и разделителям строк Юникода — и номера
        разъехались бы."""
        if path not in self.lines_cache:
            self.lines_cache[path] = _LINE_BREAK.split(self.sources[path].removesuffix("\n"))
        return self.lines_cache[path]

    def _code_line(self, path: str, number: int) -> str:
        """Строка number файла без комментария; за концом файла — пустая."""
        lines = self._source_lines(path)
        return uncomment(lines[number - 1]) if 1 <= number <= len(lines) else ""

    def _code(self, path: str) -> str:
        """Файл без комментариев."""
        if path not in self.code_cache:
            self.code_cache[path] = "\n".join(map(uncomment, self._source_lines(path)))
        return self.code_cache[path]

    def _warning(self, index: int, first: str) -> None:
        parts = [first]
        for following in self.lines[index + 1 : index + _MAX_WARNING_LINES]:
            match = _CONTINUATION.match(following)
            if not following.strip() or match is None:
                break
            parts.append(match["text"])
        message = " ".join(part.strip() for part in parts)
        line = None
        if match := _INPUT_LINE.search(message):
            line = int(match["line"])
            message = message[: match.start()]
        self._add(message.rstrip("."), self._current_file() if line else None, line, "warning")

    def _undefined_command(self, index: int) -> str | None:
        for following in self.lines[index + 1 : index + 1 + _LOOKAHEAD_LINES]:
            if match := _LINE_REF.match(following):
                found = _LAST_COMMAND.search(match["text"] or "")
                return found[1] if found else None
        return None

    def _add(self, message: str, file: str | None, line: int | None, severity: Severity) -> None:
        message = message.strip()[:MAX_MESSAGE_CHARS]
        # Строка без файла проекта — строка в пакете или классе: пользователю она не поможет.
        line = line if file is not None else None
        key = (file, line, message, severity)
        # Лишнее не копим: в логе зациклившегося документа предупреждений бывают тысячи.
        if key in self.seen or self.counts[severity] >= MAX_ENTRIES:
            return
        self.seen.add(key)
        self.counts[severity] += 1
        context = self._context(file, line)
        self.entries.append(
            BuildError(file=file, line=line, message=message, context=context, severity=severity)
        )

    def _context(self, file: str | None, line: int | None) -> str:
        """До 10 строк до и после места ошибки, с номерами; строка ошибки — с «>»."""
        if file is None or line is None or file not in self.sources:
            return ""
        source = self._source_lines(file)
        if not 1 <= line <= len(source):
            return ""
        first, last = max(1, line - CONTEXT_LINES), min(len(source), line + CONTEXT_LINES)
        width = len(str(last))
        return "\n".join(
            f"{'>' if number == line else ' '} {number:>{width}} | "
            f"{source[number - 1].rstrip()[:MAX_CONTEXT_LINE_CHARS]}"
            for number in range(first, last + 1)
        )

    def _project_path(self, logged: str) -> str | None:
        """Путь в проекте по пути из лога («./sections/a.tex» → «sections/a.tex») или None."""
        path = logged.removeprefix("./")
        return path if path in self.sources else None

    def _current_file(self) -> str | None:
        """Файл, который TeX читает сейчас, — верхний в стеке.

        None, если сверху системный файл (пакет, класс): «input line N» и «l.N» тогда
        про строку в нём, и приписать их файлу проекта под ним было бы неправдой.
        """
        return self.stack[-1] if self.stack else None

    def _track_files(self, line: str) -> None:
        for match in _PARENS.finditer(line):
            if match[0] == ")":
                if self.stack:
                    closed = self.stack.pop()
                    if closed is not None and closed not in self.closed:
                        self.closed.append(closed)
                continue
            self.stack.append(self._opened_file(line, match.end()))

    def _opened_file(self, line: str, start: int) -> str | None:
        """Файл проекта, который открывает «(» перед line[start:], или None.

        Имя тянется до скобки или конца строки, но в именах бывают пробелы, а после
        имени TeX тоже ставит пробел. Поэтому пробуем каждую границу, от самой дальней, —
        это поиск в словаре, а не перебор всех файлов проекта на каждую скобку.
        Строка не копируется: в логе зациклившегося документа скобок бывают миллионы.
        """
        name = _UNTIL_PAREN.match(line, start)
        candidate = (name[0] if name else "").removeprefix("./")
        ends = [len(candidate), *(i for i, char in enumerate(candidate) if char == " ")]
        for end in sorted(ends, reverse=True):
            if candidate[:end] in self.sources:
                return candidate[:end]
        return None


def uncomment(line: str) -> str:
    """Строка без комментария TeX; «\\\\» перед ним остаются."""
    return _COMMENT.sub(r"\1", line)


def parse_log(log: bytes, sources: dict[str, str], engine: Engine) -> ParsedLog:
    """Ошибки и предупреждения из лога и число страниц PDF.

    sources — текстовые файлы проекта (путь → содержимое): по ним файлы из лога
    сопоставляются с проектом и берётся контекст вокруг ошибки. engine нужен,
    чтобы правильно склеить перенесённые строки.
    """
    return _Parser(sources, unwrap(log[:MAX_LOG_BYTES], engine)).parse()


def unwrap(log: bytes, engine: Engine) -> list[str]:
    """Строки лога, склеенные обратно там, где TeX их перенёс.

    TeX переносит строку ровно на 79 позициях: XeTeX считает символы, pdfTeX — байты
    (проверено на образе компилятора). Склеиваем байты и декодируем уже целую строку:
    так перенос посреди русской буквы у pdfTeX не превращается в мусор.
    """
    lines: list[str] = []
    pending = b""
    for raw in log.split(b"\n"):
        raw = raw.removesuffix(b"\r")
        pending += raw
        width = len(raw) if engine == "pdflatex" else len(raw.decode(errors="replace"))
        if width == MAX_PRINT_LINE:
            continue
        lines.append(pending.decode(errors="replace"))
        pending = b""
    if pending:
        lines.append(pending.decode(errors="replace"))
    return lines


def _limit(entries: list[BuildError]) -> list[BuildError]:
    """Не больше MAX_ENTRIES: все ошибки (их уже не больше MAX_ENTRIES), на остаток —
    предупреждения. Порядок — как в логе."""
    room = MAX_ENTRIES - sum(entry.severity == "error" for entry in entries)
    kept: list[BuildError] = []
    for entry in entries:
        if entry.severity == "warning":
            if room <= 0:
                continue
            room -= 1
        kept.append(entry)
    return kept
