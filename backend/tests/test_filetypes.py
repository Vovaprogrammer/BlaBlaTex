"""Тип загруженного файла по содержимому и перекодировка текста (projects/filetypes.py)."""

import codecs
import io

import pytest

from app.core.errors import AppError
from app.modules.projects.filetypes import (
    DOCX_MIME,
    PPTX_MIME,
    XLSX_MIME,
    check_binary,
    decode_text,
    detect,
)
from tests.file_samples import DOCX, JPEG, OLE, PDF, PNG, PPTX, SVG, XLSX, ZIP


def _unknown_zip_version() -> bytes:
    """Документ, которому якобы нужна версия zip 9.9: zipfile отвечает NotImplementedError."""
    data = bytearray(DOCX)
    data[data.find(b"PK\x01\x02") + 6] = 99
    return bytes(data)


def rejected(path: str, data: bytes) -> str:
    """Сообщение 415 о бинарном файле; заодно проверяет, что ошибка называет файл."""
    with pytest.raises(AppError) as caught:
        check_binary(path, io.BytesIO(data))
    assert (caught.value.status, caught.value.details) == (415, {"path": path})
    return caught.value.message


def rejected_text(path: str, data: bytes) -> str:
    with pytest.raises(AppError) as caught:
        decode_text(path, data)
    assert (caught.value.status, caught.value.details) == (415, {"path": path})
    return caught.value.message


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (PDF, "application/pdf"),
        (SVG, "image/svg+xml"),
        (DOCX, DOCX_MIME),
        (PPTX, PPTX_MIME),
        (XLSX, XLSX_MIME),
    ],
)
def test_types_from_9_8_are_detected_by_content(data: bytes, mime: str) -> None:
    assert detect(io.BytesIO(data)) == mime


def test_detection_reads_file_from_start() -> None:
    file = io.BytesIO(PNG)
    file.seek(5)

    assert detect(file) == "image/png"


def test_pdf_header_may_follow_a_few_bytes() -> None:
    # По стандарту PDF заголовок ищется в первых 1024 байтах.
    assert detect(io.BytesIO(b"\r\n" * 10 + PDF)) == "application/pdf"


@pytest.mark.parametrize(
    "start",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"/>',
        codecs.BOM_UTF8 + b"\n  <svg>",
        b'<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd"><svg>',
        b'<!DOCTYPE svg [<!ENTITY a "b">]>\n<!-- one --><!-- two -->\n<SVG width="1">',
    ],
)
def test_svg_is_text_starting_with_svg_tag(start: bytes) -> None:
    assert detect(io.BytesIO(start)) == "image/svg+xml"


@pytest.mark.parametrize("data", [b"<html><svg></svg></html>", b"svg", b"", b"plain text"])
def test_unknown_content_is_not_detected(data: bytes) -> None:
    assert detect(io.BytesIO(data)) is None


@pytest.mark.parametrize("path", ["photo.jpg", "photo.JPEG"])
def test_jpg_and_jpeg_are_one_type(path: str) -> None:
    assert check_binary(path, io.BytesIO(JPEG)) == "image/jpeg"


def test_extension_must_match_content_with_rename_hint() -> None:
    assert rejected("figures/screen.jpg", PNG) == (
        "Файл figures/screen.jpg — на самом деле картинка PNG. Переименуйте его в screen.png"
    )
    assert "таблица Excel" in rejected("task.docx", XLSX)
    assert "task.xlsx" in rejected("task.docx", XLSX)


def test_old_office_format_asks_to_resave() -> None:
    message = rejected("task.docx", OLE)

    assert "старого формата" in message
    assert message.endswith("Сохраните его заново в формате .docx")


@pytest.mark.parametrize(
    "data",
    [ZIP, b"PK\x03\x04 broken zip", _unknown_zip_version(), b"", b"MZ\x90\x00 program"],
)
def test_damaged_or_other_content_is_rejected(data: bytes) -> None:
    assert rejected("task.docx", data) == "Файл task.docx повреждён или это не документ Word"


# Текстовые файлы.


def test_utf8_is_kept_and_bom_removed() -> None:
    assert decode_text("lab.py", "print('Привет')\n".encode()) == "print('Привет')\n"
    assert decode_text("lab.py", codecs.BOM_UTF8 + "# Код\n".encode()) == "# Код\n"


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be"])
def test_utf16_with_bom_becomes_utf8(encoding: str) -> None:
    # Так сохраняет вывод программы Windows PowerShell (>).
    bom = codecs.BOM_UTF16_BE if encoding == "utf-16-be" else b""
    data = bom + "Результат: 42\n".encode(encoding)

    assert decode_text("output.txt", data) == "Результат: 42\n"


def test_cp1251_from_windows_is_converted() -> None:
    data = "// Сортировка пузырьком\nint main() {}\n".encode("cp1251")

    assert decode_text("lab.cpp", data) == "// Сортировка пузырьком\nint main() {}\n"


def test_line_endings_become_lf() -> None:
    assert decode_text("lab.c", b"a\r\nb\rc\n\r\n") == "a\nb\nc\n\n"


def test_binary_signature_under_text_extension() -> None:
    assert rejected_text("notes.txt", PNG) == "Файл notes.txt — картинка PNG, а не текст"
    assert "архив ZIP" in rejected_text("data.csv", DOCX)


@pytest.mark.parametrize(
    "data",
    [b"abc\x00def", "ab".encode("utf-16-le"), codecs.BOM_UTF16_LE + b"a\x00\x00\x00"],
)
def test_nul_characters_mean_binary(data: bytes) -> None:
    assert rejected_text("main.c", data).startswith("Файл main.c похож на двоичный")


def test_unknown_encoding_is_rejected() -> None:
    # 0x98 нет ни в UTF-8 (одиночный байт продолжения), ни в cp1251.
    assert rejected_text("main.c", b"x\x98") == (
        "Не удалось прочитать текст файла main.c: сохраните его в кодировке UTF-8"
    )
