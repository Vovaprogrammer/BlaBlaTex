"""Маленькие синтетические файлы типов 9.8 для тестов загрузки: настоящие материалы не нужны."""

import io
import zipfile

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR fake image"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00 fake photo"
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<!-- Схема алгоритма -->\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>\n'
).encode()
# Документ Office до 2007 года (.doc): контейнер OLE.
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(24)


def zipped(*names: str) -> bytes:
    """Zip-архив с пустыми файлами по этим путям."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "<x/>")
    return buffer.getvalue()


# Документы Office (OOXML) — zip с [Content_Types].xml и главной частью в папке своего вида.
DOCX = zipped("[Content_Types].xml", "word/document.xml")
PPTX = zipped("[Content_Types].xml", "ppt/presentation.xml")
XLSX = zipped("[Content_Types].xml", "xl/workbook.xml")
ZIP = zipped("readme.txt")
