"""Правила путей файлов проекта (architecture.md 9.8). Без FastAPI: их проверяет и сервис."""

import unicodedata
from pathlib import PurePosixPath

MAX_PATH_LENGTH = 255
MAX_SEGMENT_LENGTH = 100
# Предел имени файла в Linux (NAME_MAX): длиннее — проект не разложить по папкам для сборки.
# 100 букв кириллицы — 200 байт, а 100 эмодзи — уже 400.
MAX_SEGMENT_BYTES = 255
# Категории Unicode: управляющие (Cc), невидимые символы форматирования вроде смены
# направления текста (Cf), половинки суррогатных пар (Cs), разделители строк и абзацев
# (Zl, Zp). С ними два одинаковых на вид имени — разные файлы, а имя на экране обманывает.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
# latexmk выполняет latexmkrc из папки сборки как код на Perl. Регистр не учитываем:
# на файловой системе без учёта регистра LATEXMKRC — тот же файл.
_FORBIDDEN_NAMES = frozenset({"latexmkrc"})
_FORBIDDEN_CHARS = frozenset("\\:")
# Спецсимволы TeX: с % # { } " в имени файл не подключить через \input, \includegraphics
# и \lstinputlisting (проверено на образе компилятора), остальные ломают текст документа,
# если имя файла в него попадёт.
_TEX_SPECIAL_CHARS = frozenset('%#~$&^{}`"')


# Типы файлов, которые пишутся текстом (9.8): документ LaTeX, данные и код. Картинки
# и документы (.png .jpg .jpeg .svg .pdf .docx .pptx .xlsx) приходят загрузкой — B2.2.
TEXT_FILE_EXTENSIONS = (
    *(".tex", ".bib", ".sty", ".cls", ".txt", ".md", ".csv"),
    *(".py", ".java", ".c", ".cpp", ".h", ".js", ".ts", ".sql", ".go", ".rs", ".kt", ".cs"),
)


class InvalidPathError(ValueError):
    """Путь нарушает правила 9.8. Текст ошибки — для пользователя, на русском."""


def is_text_file_type(path: str) -> bool:
    """Можно ли хранить файл текстом: расширение из 9.8, регистр не важен."""
    return PurePosixPath(path).suffix.lower() in TEXT_FILE_EXTENSIONS


def validate_path(path: str) -> str:
    """Проверяет путь файла или папки и возвращает его в форме NFC.

    Разделитель — /. Запрещены: ведущий /, части «.», «..» и пустые, символы \\ и :,
    спецсимволы TeX, управляющие и невидимые символы, скрытые имена (с точки в начале)
    и имя latexmkrc.
    """
    # Одна и та же буква «й» бывает одним символом или двумя (macOS присылает второй вариант).
    path = unicodedata.normalize("NFC", path)
    if not path:
        raise InvalidPathError("Путь не может быть пустым")
    if len(path) > MAX_PATH_LENGTH:
        raise InvalidPathError(f"Путь длиннее {MAX_PATH_LENGTH} символов")
    if path.startswith("/"):
        raise InvalidPathError("Путь не может начинаться с /")
    for char in path:
        if char in _FORBIDDEN_CHARS:
            raise InvalidPathError(f"Символ {char} в пути запрещён")
        if char in _TEX_SPECIAL_CHARS:
            raise InvalidPathError(f"Символ {char} в имени ломает сборку LaTeX — уберите его")
        if unicodedata.category(char) in _FORBIDDEN_CATEGORIES:
            raise InvalidPathError("Управляющие и невидимые символы в пути запрещены")
    for segment in path.split("/"):
        if not segment:
            raise InvalidPathError("В пути не может быть двух / подряд или / в конце")
        if segment in (".", ".."):
            raise InvalidPathError("Части пути «.» и «..» запрещены")
        if segment.startswith("."):
            raise InvalidPathError("Имя файла или папки не может начинаться с точки")
        if segment.casefold() in _FORBIDDEN_NAMES:
            raise InvalidPathError("Имя latexmkrc запрещено")
        if len(segment) > MAX_SEGMENT_LENGTH:
            raise InvalidPathError(f"Имя файла или папки длиннее {MAX_SEGMENT_LENGTH} символов")
        if len(segment.encode()) > MAX_SEGMENT_BYTES:
            raise InvalidPathError(
                "Имя файла или папки слишком длинное: сократите его или уберите эмодзи"
            )
    return path
