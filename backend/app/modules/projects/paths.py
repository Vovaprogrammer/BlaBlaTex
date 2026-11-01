"""Правила путей файлов проекта (architecture.md 9.8). Без FastAPI: их проверяет и сервис."""

import unicodedata

MAX_PATH_LENGTH = 255
MAX_SEGMENT_LENGTH = 100
# latexmk выполняет latexmkrc из папки сборки как код на Perl. Регистр не учитываем:
# на файловой системе без учёта регистра LATEXMKRC — тот же файл.
_FORBIDDEN_NAMES = frozenset({"latexmkrc"})
_FORBIDDEN_CHARS = frozenset("\\:")


class InvalidPathError(ValueError):
    """Путь нарушает правила 9.8. Текст ошибки — для пользователя, на русском."""


def validate_path(path: str) -> str:
    """Проверяет путь файла или папки и возвращает его в форме NFC.

    Разделитель — /. Запрещены: ведущий /, части «.», «..» и пустые, символы \\ и :,
    управляющие символы, скрытые имена (с точки в начале) и имя latexmkrc.
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
        if unicodedata.category(char) == "Cc":
            raise InvalidPathError("Управляющие символы в пути запрещены")
    for segment in path.split("/"):
        if not segment:
            raise InvalidPathError("В пути не может быть двух / подряд или / в конце")
        if segment in (".", ".."):
            raise InvalidPathError("Части пути «.» и «..» запрещены")
        if segment.startswith("."):
            raise InvalidPathError("Имя файла или папки не может начинаться с точки")
        if segment.casefold() in _FORBIDDEN_NAMES:
            raise InvalidPathError(f"Имя {segment} запрещено")
        if len(segment) > MAX_SEGMENT_LENGTH:
            raise InvalidPathError(f"Имя файла или папки длиннее {MAX_SEGMENT_LENGTH} символов")
    return path
