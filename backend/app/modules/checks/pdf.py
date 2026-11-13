"""Проверки по итогу и логу сборки (docs/checks.md): build-failed, text-overflow,
missing-glyph. Лог читает тот же разбор, что ошибки сборки (builds/log_parser.py)."""

from collections.abc import Iterator

from app.modules.checks.context import Context, Found

BUILD_ERROR = (
    "PDF не собрался: в сборке ошибок — {count}. Откройте ошибки сборки или попросите ИИ их "
    "исправить."
)
BUILD_TIMEOUT = (
    "Сборка не уложилась во время, PDF не обновился. Чаще всего мешают очень большие "
    "картинки: сожмите их или сохраните в JPEG."
)
OVERFLOW_PARAGRAPH = (
    "Текст выходит за правое поле на {mm} мм. Обычно мешает длинное слово без пробелов — "
    "имя функции, путь или адрес. Попросите ИИ перефразировать или разбить его."
)
OVERFLOW_TABLE = (
    "Таблица шире страницы на {mm} мм. Попросите ИИ сократить заголовки столбцов или разбить "
    "таблицу."
)
MISSING_GLYPH = (
    "Символа «{char}» нет в шрифте отчёта, и в PDF он пропал. Замените его словом или обычным "
    "знаком, например «✅» на «[OK]», или уберите. Если символ в вашем коде или выводе "
    "программы — исправьте материал или оставьте как есть."
)

# Меньше 1 мм (2,85 pt) на печати не видно.
MIN_OVERFLOW_PT = 2.85
_MM_PER_PT = 25.4 / 72.27


def build_failed(context: Context) -> Iterator[Found]:
    build = context.build
    if build is None or build.status == "ok":
        return
    if build.status == "timeout":
        message = BUILD_TIMEOUT
    else:
        message = BUILD_ERROR.format(count=max(build.errors, 1))
    yield Found("build-failed", message, place="build")


def text_overflow(context: Context) -> Iterator[Found]:
    parsed = context.parsed_log
    if parsed is None:
        return
    seen: set[tuple[str, int, int, str]] = set()
    for box in parsed.overfull:
        if box.points <= MIN_OVERFLOW_PT or box.file is None:
            continue
        # longtable пишет одну и ту же строку лога по нескольку раз.
        key = (box.file, box.first, box.last, box.kind)
        if key in seen:
            continue
        seen.add(key)
        mm = f"{box.points * _MM_PER_PT:.1f}".replace(".", ",")
        if box.kind == "alignment":
            file, line = _table_start(context, box.file, box.first, box.last)
            message = OVERFLOW_TABLE.format(mm=mm)
        else:
            file, line = _code_macro(context, box.file) or _paragraph_start(
                context, box.file, box.first, box.last
            )
            message = OVERFLOW_PARAGRAPH.format(mm=mm)
        yield Found("text-overflow", message, file, line)


def _paragraph_start(context: Context, file: str, first: int, last: int) -> tuple[str, int]:
    """Где начался абзац «at lines first--last»: лог называет файл, где абзац кончился.
    Последний абзац раздела кончается на \\section следующего файла — «lines 7--1»:
    начало больше конца, значит, абзац начался в файле, прочитанном раньше."""
    if first <= last:
        return file, first
    earlier = context.report.earlier_file(file, last, first)
    return (earlier, first) if earlier is not None else (file, last)


def _table_start(context: Context, file: str, first: int, last: int) -> tuple[str, int]:
    """У bbttable лог называет строку \\end{bbttable} — находка ставится на её \\begin."""
    report = context.report
    for env in report.envs:
        if env.name != "bbttable":
            continue
        end_file, end_line = report.locate(env.end - 1)
        if end_file == file and first <= end_line <= last:
            return report.locate(env.start)
    return file, first


def _code_macro(context: Context, file: str) -> tuple[str, int] | None:
    """Строка \\bbtCodeFile или \\lstinputlisting, которым вставлен файл кода, или None."""
    report = context.report
    for use in report.uses:
        if use.kind == "code" and use.path == file:
            return report.locate(use.start)
    return None


def missing_glyph(context: Context) -> Iterator[Found]:
    parsed = context.parsed_log
    if parsed is None:
        return
    seen: set[tuple[str, str | None]] = set()
    for missing in parsed.missing_chars:
        place = _glyph_place(context, missing.file, missing.char)
        if place is None:
            continue
        file, line = place
        if (missing.char, file) in seen:
            continue
        seen.add((missing.char, file))
        yield Found("missing-glyph", MISSING_GLYPH.format(char=missing.char), file, line)


def _glyph_place(context: Context, file: str | None, char: str) -> tuple[str, int | None] | None:
    """Где символ: строка макроса, если открыт файл кода; первая строка открытого файла
    с этим символом; иначе первая такая строка в файлах отчёта."""
    if file is not None and (macro := _code_macro(context, file)) is not None:
        return macro
    texts = context.snapshot.texts
    files = [file] if file is not None and file in texts else []
    files += [path for path in context.report.files if path not in files]
    for path in files:
        for number, line in enumerate(texts.get(path, "").split("\n"), start=1):
            if char in line:
                return path, number
    if file is not None and file in texts:
        return file, None
    return None
