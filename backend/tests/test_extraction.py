"""Извлечение текста из материалов (architecture.md 5): pdfminer, markitdown, отдельный
процесс, текст как есть, лимиты и понятные ошибки."""

from pathlib import Path

import pytest
from pdfminer.pdfdocument import PDFPasswordIncorrect

from app.modules.materials import convert as converter
from app.modules.materials import extraction
from app.modules.materials.extraction import (
    ARCHIVE_MESSAGE,
    BROKEN_MESSAGE,
    NO_TEXT_MESSAGE,
    PASSWORD_MESSAGE,
    SVG_MESSAGE,
    TIMEOUT_MESSAGE,
    TOO_COMPLEX_MESSAGE,
    UNSUPPORTED_MESSAGE,
    ConverterOutput,
    Extracted,
    ExtractionFailed,
    Limits,
    extract,
)
from app.modules.projects.filetypes import DOCX_MIME, PPTX_MIME, XLSX_MIME
from tests.material_samples import PNG_1X1, make_docx, make_pdf, make_pptx, make_xlsx

PDF_MIME = "application/pdf"
TEXT_MIME = "text/plain"
CONVERTER_OPTIONS = {
    "memory_mb": 1024,
    "max_chars": 1000,
    "max_unpacked_bytes": 10**6,
    "max_parts": 100,
}


async def test_text_and_code_are_kept_as_is() -> None:
    code = "def greet():\n    return 'привет'\n"

    assert await extract(TEXT_MIME, code) == Extracted(text=code, pages=None, method="text")


async def test_long_text_is_cut_at_line_end_with_note() -> None:
    # 10 строк по 9 символов и 90 строк по 10: всего 990, в первые 100 входят 11 строк.
    content = "".join(f"строка {number}\n" for number in range(100))

    extracted = await extract(TEXT_MIME, content, Limits(max_chars=100))

    assert extracted.text == (
        content[:99] + "\n\n[Текст обрезан: сохранены первые 99 символов из 990.]"
    )


async def test_long_line_is_cut_at_limit() -> None:
    extracted = await extract(TEXT_MIME, "я" * 1500, Limits(max_chars=100))

    assert (
        extracted.text == "я" * 100 + "\n\n[Текст обрезан: сохранены первые 100 символов из 1 500.]"
    )


async def test_long_document_is_cut_with_note() -> None:
    paragraphs = [f"Абзац номер {number} с текстом задания." for number in range(50)]

    extracted = await extract(DOCX_MIME, make_docx(paragraphs), Limits(max_chars=200))

    assert extracted.text is not None
    assert extracted.text.startswith("Абзац номер 0")
    assert "[Текст обрезан: сохранены первые" in extracted.text
    assert len(extracted.text) < 300


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg"])
async def test_screenshot_has_no_text(mime: str) -> None:
    assert await extract(mime, PNG_1X1) == Extracted(text=None, pages=None, method="image")


async def test_svg_fails_with_advice() -> None:
    with pytest.raises(ExtractionFailed) as failed:
        await extract("image/svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg'/>")

    assert failed.value.message == SVG_MESSAGE


async def test_unknown_binary_type_fails() -> None:
    with pytest.raises(ExtractionFailed) as failed:
        await extract("application/zip", b"PK\x03\x04")

    assert failed.value.message == UNSUPPORTED_MESSAGE


async def test_pdf_without_text_is_a_scan() -> None:
    with pytest.raises(ExtractionFailed) as failed:
        await extract(PDF_MIME, make_pdf([" ", " "]))

    assert failed.value.message == NO_TEXT_MESSAGE


@pytest.mark.parametrize(
    "limits",
    [Limits(max_unpacked_bytes=100), Limits(max_parts=2)],
    ids=["unpacked-size", "parts"],
)
async def test_office_archive_over_limits_is_not_parsed(limits: Limits) -> None:
    with pytest.raises(ExtractionFailed) as failed:
        await extract(DOCX_MIME, make_docx(["бомба"]), limits)

    assert failed.value.message == ARCHIVE_MESSAGE


def test_converter_cleans_null_and_lone_surrogates() -> None:
    assert converter.clean("a\x00b\ud800c") == "ab?c"


@pytest.mark.parametrize(
    ("error", "code"),
    [(PDFPasswordIncorrect(), "password"), (MemoryError(), "too_complex")],
    ids=["password", "memory"],
)
def test_converter_names_known_failures(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: str
) -> None:
    def fail(data: bytes) -> converter.Result:
        raise error

    monkeypatch.setattr(converter, "convert_pdf", fail)

    assert converter.convert("pdf", b"%PDF", CONVERTER_OPTIONS)["error"] == code


@pytest.mark.parametrize(
    ("code", "message"),
    [("password", PASSWORD_MESSAGE), ("too_complex", TOO_COMPLEX_MESSAGE)],
)
async def test_known_failure_gets_its_message(
    monkeypatch: pytest.MonkeyPatch, code: str, message: str
) -> None:
    async def converted(kind: str, data: bytes, limits: Limits) -> ConverterOutput:
        return ConverterOutput(error=code)

    monkeypatch.setattr(extraction, "_convert", converted)

    with pytest.raises(ExtractionFailed) as failed:
        await extract(PDF_MIME, b"%PDF")

    assert failed.value.message == message


async def test_crashed_converter_means_too_complex(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    crash = tmp_path / "crash.py"
    crash.write_text("import sys\nsys.exit(3)\n")
    monkeypatch.setattr(extraction, "CONVERTER", crash)

    with pytest.raises(ExtractionFailed) as failed:
        await extract(PDF_MIME, make_pdf(["Hi"]))

    assert failed.value.message == TOO_COMPLEX_MESSAGE
    assert failed.value.detail["returncode"] == 3


async def test_garbled_converter_output_is_broken_without_quoting_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Библиотека разбора напечатала своё в stdout — вместе с текстом файла.
    garbled = tmp_path / "garbled.py"
    garbled.write_text("print('warning')\nprint('{\"text\": \"secret from the file')\n")
    monkeypatch.setattr(extraction, "CONVERTER", garbled)

    with pytest.raises(ExtractionFailed) as failed:
        await extract(PDF_MIME, make_pdf(["Hi"]))

    assert failed.value.message == BROKEN_MESSAGE
    assert failed.value.detail == {"reason": "bad_output", "kind": "pdf"}
    # Ни в сообщении, ни в причине, ни в цепочке исключений нет вывода процесса.
    assert failed.value.__cause__ is None
    assert failed.value.__suppress_context__


async def test_pdf_text_has_page_markers_and_page_count() -> None:
    extracted = await extract(PDF_MIME, make_pdf(["First page", "Second page"]))

    assert extracted.method == "pdfminer"
    assert extracted.pages == 2
    assert extracted.text == "<!-- Страница 1 -->\nFirst page\n\n<!-- Страница 2 -->\nSecond page"


async def test_pdf_empty_page_keeps_its_marker() -> None:
    extracted = await extract(PDF_MIME, make_pdf(["One", " ", "Three"]))

    assert extracted.pages == 3
    assert extracted.text is not None
    assert "<!-- Страница 2 -->\n\n<!-- Страница 3 -->\nThree" in extracted.text


async def test_docx_becomes_markdown_with_cyrillic() -> None:
    extracted = await extract(DOCX_MIME, make_docx(["Лабораторная работа №3", "Задание"]))

    assert extracted.method == "markitdown"
    assert extracted.pages is None
    assert extracted.text is not None
    assert "Лабораторная работа №3" in extracted.text
    assert "Задание" in extracted.text


async def test_pptx_pages_are_slides() -> None:
    extracted = await extract(PPTX_MIME, make_pptx(["Цель работы", "Выводы"]))

    assert extracted.method == "markitdown"
    assert extracted.pages == 2
    assert extracted.text is not None
    assert "<!-- Slide number: 1 -->" in extracted.text
    assert "# Выводы" in extracted.text


async def test_xlsx_sheets_become_tables() -> None:
    data = make_xlsx({"Измерения": [["t", "U"], [1, 5]], "Итог": [["среднее"]]})

    extracted = await extract(XLSX_MIME, data)

    assert extracted.method == "markitdown"
    assert extracted.text is not None
    assert "## Измерения" in extracted.text
    assert "| t | U |" in extracted.text
    assert "## Итог" in extracted.text


@pytest.mark.parametrize(
    ("mime", "data"),
    [
        (PDF_MIME, b"%PDF-1.4\nnot really a pdf"),
        (PDF_MIME, make_pdf(["Cut"])[:200]),
        (DOCX_MIME, b"PK\x03\x04not a zip"),
        (PPTX_MIME, make_docx(["не презентация"])),
        (XLSX_MIME, b"PK\x03\x04not a zip"),
    ],
    ids=["pdf-garbage", "pdf-truncated", "docx-garbage", "pptx-wrong-parts", "xlsx-garbage"],
)
async def test_broken_document_fails_with_clear_message(mime: str, data: bytes) -> None:
    with pytest.raises(ExtractionFailed) as failed:
        await extract(mime, data)

    assert failed.value.message == BROKEN_MESSAGE
    # Для лога — где упал разбор, а не текст исключения: в нём мог быть кусок файла.
    assert failed.value.detail["error_type"]
    assert "Traceback" not in str(failed.value.detail["trace"])


async def test_slow_document_is_killed_by_timeout() -> None:
    # Процесс разбора не успеет даже загрузить markitdown.
    with pytest.raises(ExtractionFailed) as failed:
        await extract(DOCX_MIME, make_docx(["долго"]), Limits(timeout_s=0.05))

    assert failed.value.message == TIMEOUT_MESSAGE
    assert failed.value.detail["reason"] == "timeout"
