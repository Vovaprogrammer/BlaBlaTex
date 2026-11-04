"""Извлечение текста из документов (architecture.md 5): pdfminer, markitdown, отдельный процесс."""

import pytest

from app.modules.materials.extraction import (
    BROKEN_MESSAGE,
    TIMEOUT_MESSAGE,
    ExtractionFailed,
    Limits,
    extract,
)
from app.modules.projects.filetypes import DOCX_MIME, PPTX_MIME, XLSX_MIME
from tests.material_samples import make_docx, make_pdf, make_pptx, make_xlsx

PDF_MIME = "application/pdf"


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
