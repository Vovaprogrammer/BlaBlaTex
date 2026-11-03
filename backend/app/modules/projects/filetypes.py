"""Тип загруженного файла по содержимому и текст текстовых файлов (architecture.md 9.1, 9.8).

Тип называет расширение, а содержимое должно ему соответствовать: картинка под именем .pdf
или программа под именем .png не сохраняются. Проверка — по сигнатурам в начале файла,
у документов Office — по оглавлению zip-архива. Библиотеки вроде python-magic не нужны:
типов в 9.8 всего восемь, а libmagic плохо ставится на Windows и нужна в образе отдельно.
Без FastAPI и базы: функции работают с байтами и открытым файлом.
"""

import codecs
import re
import zipfile
from pathlib import PurePosixPath
from typing import BinaryIO

from app.core.errors import AppError, ErrorCode
from app.modules.projects.paths import BINARY_FILE_TYPES

# Сколько байт с начала файла смотреть: сигнатуры и начало SVG.
HEAD_BYTES = 4096

DOCX_MIME = BINARY_FILE_TYPES[".docx"]
PPTX_MIME = BINARY_FILE_TYPES[".pptx"]
XLSX_MIME = BINARY_FILE_TYPES[".xlsx"]
# Чем ещё может оказаться файл: типов нет в 9.8, они нужны для понятного сообщения.
_ZIP_MIME = "application/zip"
_OLE_MIME = "application/x-ole-storage"

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_PDF = b"%PDF-"
_ZIP = b"PK\x03\x04"
# Документ Office до 2007 года (.doc, .xls, .ppt) — контейнер OLE.
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# Начало SVG: необязательные BOM, объявление XML, комментарии и DOCTYPE, затем тег svg.
# Комментарий и DOCTYPE — атомарные группы (?>…): без них «.*?» при неудаче растягивал бы
# комментарий до следующего «-->», и на сотне комментариев проверка шла бы часами.
_SVG = re.compile(
    rb"(?:\xef\xbb\xbf)?\s*(?:<\?xml[^>]*>\s*)?"
    rb"(?:(?><!--.*?-->|<!DOCTYPE[^>\[]*(?:\[.*?\])?\s*>)\s*)*<svg[\s>/]",
    re.DOTALL | re.IGNORECASE,
)
# Сигнатуры, с которых не начинается текст: по ним картинку под именем .txt видно сразу.
_BINARY_SIGNATURES = {
    _PNG: "image/png",
    _JPEG: "image/jpeg",
    _PDF: "application/pdf",
    _ZIP: _ZIP_MIME,
    _OLE: _OLE_MIME,
}
# Документ Office (OOXML) — zip с [Content_Types].xml и папкой своего вида.
_OOXML_FOLDERS = {"word/": DOCX_MIME, "ppt/": PPTX_MIME, "xl/": XLSX_MIME}
# Конец zip: запись с размером оглавления. Она в последних 22 байтах или перед комментарием
# архива до 64 КБ.
_ZIP_END = b"PK\x05\x06"
_ZIP_END_SIZE = 22
_ZIP64_LOCATOR = b"PK\x06\x07"
# В документе Office сотни частей, оглавление — десятки килобайт. Оглавление больше zipfile
# разбирал бы в память целиком: 20 МБ крошечных записей — это сотни мегабайт.
_MAX_ZIP_DIRECTORY = 1024 * 1024
_TYPE_NAMES = {
    "image/png": "картинка PNG",
    "image/jpeg": "картинка JPEG",
    "image/svg+xml": "картинка SVG",
    "application/pdf": "документ PDF",
    DOCX_MIME: "документ Word",
    PPTX_MIME: "презентация PowerPoint",
    XLSX_MIME: "таблица Excel",
    _ZIP_MIME: "архив ZIP",
    _OLE_MIME: "документ Office старого формата (.doc, .xls или .ppt)",
}


def detect(file: BinaryIO) -> str | None:
    """Чем файл оказался по содержимому: MIME из 9.8, zip, OLE или None — не узнали."""
    file.seek(0)
    head = file.read(HEAD_BYTES)
    if head.startswith(_PNG):
        return "image/png"
    if head.startswith(_JPEG):
        return "image/jpeg"
    if head.startswith(_OLE):
        return _OLE_MIME
    if head.startswith(_ZIP):
        return _zip_type(file)
    if _SVG.match(head):
        return "image/svg+xml"
    # По стандарту PDF заголовок может стоять не в самом начале, а в первых 1024 байтах.
    # Поэтому PDF — последним: «%PDF-» бывает и внутри zip или текста SVG.
    if _PDF in head[:1024]:
        return "application/pdf"
    return None


def check_binary(path: str, file: BinaryIO) -> str:
    """MIME бинарного файла по расширению path, если содержимое ему соответствует. Нет — 415.

    .jpg и .jpeg — один тип. Файл читается только с начала, а у zip — его оглавление.
    """
    expected = BINARY_FILE_TYPES[PurePosixPath(path).suffix.lower()]
    actual = detect(file)
    if actual == expected:
        return expected
    if actual in BINARY_FILE_TYPES.values():
        extension = next(ext for ext, mime in BINARY_FILE_TYPES.items() if mime == actual)
        hint = f"Переименуйте его в {PurePosixPath(path).with_suffix(extension).name}"
        raise unsupported(path, f"Файл {path} — на самом деле {_TYPE_NAMES[actual]}. {hint}")
    if actual == _OLE_MIME:
        raise unsupported(
            path,
            f"Файл {path} — {_TYPE_NAMES[actual]}. "
            f"Сохраните его заново в формате {PurePosixPath(path).suffix.lower()}",
        )
    raise unsupported(path, f"Файл {path} повреждён или это не {_TYPE_NAMES[expected]}")


def decode_text(path: str, data: bytes) -> str:
    """Текст файла path в том виде, в котором он хранится: без BOM и с переводами строк \\n.

    UTF-8 (с BOM и без) и UTF-16 с BOM читаются как есть, остальное — как cp1251: так
    сохраняют файлы Visual Studio и старые редакторы на русской Windows. XeLaTeX понимает
    только UTF-8, а агент делит строки по \\n и не нашёл бы фрагмент из файла с \\r\\n (9.4).
    Картинка, архив или двоичные данные под текстовым расширением — 415.
    """
    if data.startswith(codecs.BOM_UTF8):
        text = _decode(path, data[len(codecs.BOM_UTF8) :], "utf-8")
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        # Кодек utf-16 сам читает BOM и по нему выбирает порядок байт.
        text = _decode(path, data, "utf-16")
    else:
        actual = next(
            (mime for sign, mime in _BINARY_SIGNATURES.items() if data.startswith(sign)), None
        )
        if actual is not None:
            raise unsupported(path, f"Файл {path} — {_TYPE_NAMES[actual]}, а не текст")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if _is_damaged_utf8(data):
                raise unsupported(
                    path,
                    f"В файле {path} есть повреждённые символы. "
                    "Откройте его в редакторе и сохраните заново в кодировке UTF-8",
                ) from None
            text = _decode(path, data, "cp1251")
    # Нулевой символ в тексте не бывает, а Postgres его и не сохранит.
    if "\x00" in text:
        raise unsupported(
            path,
            f"Файл {path} похож на двоичный, а не на текст. "
            "Если это текст, сохраните его в кодировке UTF-8",
        )
    return text.replace("\r\n", "\n").replace("\r", "\n")


def unsupported(path: str, message: str) -> AppError:
    return AppError(ErrorCode.UNSUPPORTED_FILE_TYPE, message, 415, {"path": path})


def _decode(path: str, data: bytes, encoding: str) -> str:
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        raise unsupported(
            path, f"Не удалось прочитать текст файла {path}: сохраните его в кодировке UTF-8"
        ) from None


def _is_damaged_utf8(data: bytes) -> bool:
    """Текст в UTF-8 с отдельными испорченными байтами (обрезан посреди буквы, вставлен
    кусок в другой кодировке): правильных символов не из ASCII больше, чем ошибок.

    Такой файл нельзя читать как cp1251 — испортились бы все русские буквы. А у текста
    в cp1251 почти каждая русская буква — ошибка UTF-8.
    """
    lenient = data.decode("utf-8", errors="replace")
    broken = lenient.count("�")
    valid = sum(1 for char in lenient if ord(char) > 127) - broken
    return valid > broken


def _zip_directory_size(file: BinaryIO) -> int | None:
    """Размер оглавления zip из записи в конце архива; None — записи нет или это zip64."""
    size = file.seek(0, 2)
    start = max(0, size - _ZIP_END_SIZE - 0xFFFF)
    file.seek(start)
    tail = file.read()
    # Последняя запись: так её ищет и zipfile.
    at = tail.rfind(_ZIP_END)
    if at == -1 or len(tail) < at + _ZIP_END_SIZE:
        return None
    # Перед записью — указатель zip64: тогда zipfile возьмёт размер оглавления из него,
    # а не отсюда. Документам Office (меньше 4 ГБ) zip64 не нужен.
    if tail[max(0, at - 20) : at - 16] == _ZIP64_LOCATOR:
        return None
    return int.from_bytes(tail[at + 12 : at + 16], "little")


def _zip_type(file: BinaryIO) -> str:
    """Документ Word, PowerPoint или Excel — или просто zip. Распаковки нет: только оглавление."""
    directory = _zip_directory_size(file)
    if directory is None or directory > _MAX_ZIP_DIRECTORY:
        return _ZIP_MIME
    try:
        # ZipFile не закрывает переданный ему файл.
        with zipfile.ZipFile(file) as archive:
            names = archive.namelist()
    # На испорченном оглавлении zipfile бросает не только BadZipFile: неизвестная версия
    # формата — NotImplementedError, неверное имя файла в UTF-8 — UnicodeDecodeError
    # (ValueError), обрыв данных — EOFError.
    except (zipfile.BadZipFile, NotImplementedError, ValueError, EOFError):
        return _ZIP_MIME
    if "[Content_Types].xml" in names:
        for folder, mime in _OOXML_FOLDERS.items():
            if any(name.startswith(folder) for name in names):
                return mime
    return _ZIP_MIME
