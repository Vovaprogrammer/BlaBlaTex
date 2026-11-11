"""Имя отчёта для PDF и архива (architecture.md 9.1, «Имя отчёта») и заголовок
Content-Disposition с ним."""

import pytest

from app.core.http import content_disposition
from app.modules.templates.naming import report_name, safe_filename

LAB = {"work_type": "Лабораторная работа", "lab_number": 3}


def lab_name(fields: dict[str, str | int], last_name: str = "Чистяков") -> str:
    return report_name(kind="lab", title="ЛР по сетям", fields=fields, last_name=last_name)


@pytest.mark.parametrize(
    ("fields", "last_name", "expected"),
    [
        (LAB, "Чистяков", "ЛР3_Чистяков"),
        ({"work_type": "Практическая работа", "lab_number": 12}, "Чистяков", "ПР12_Чистяков"),
        # Шаблон без выбора вида работы — лабораторная.
        ({"lab_number": 3}, "Чистяков", "ЛР3_Чистяков"),
        ({"work_type": "Лабораторная работа"}, "Чистяков", "ЛР_Чистяков"),
        (LAB, "", "ЛР3"),
        (LAB, "  ", "ЛР3"),
        ({}, "", "ЛР"),
        (LAB, "Римский-Корсаков", "ЛР3_Римский-Корсаков"),
        # Номер — строка из старого проекта: пробелы по краям не попадают в имя.
        ({"lab_number": " 4 "}, "Чистяков", "ЛР4_Чистяков"),
    ],
)
def test_lab_name_from_fields_and_profile(
    fields: dict[str, str | int], last_name: str, expected: str
) -> None:
    assert lab_name(fields, last_name) == expected


def test_unknown_work_type_falls_back_to_title() -> None:
    fields = {"work_type": "Курсовая работа", "lab_number": 3}

    assert lab_name(fields) == "ЛР по сетям_Чистяков"


def test_other_kinds_use_title_and_last_name() -> None:
    name = report_name(
        kind="vkr", title="Веб-сервис для отчётов", fields={"lab_number": 3}, last_name="Чистяков"
    )

    assert name == "Веб-сервис для отчётов_Чистяков"


def test_long_title_is_cut_and_last_name_kept() -> None:
    title = "Очень длинное название работы " * 5

    name = report_name(kind="article", title=title, fields={}, last_name="Чистяков")

    assert name == f"{title[:60].strip()}_Чистяков"
    assert len(name) <= 100


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('Сети: "ЛР" 1/2 <a|b> *?', "Сети_ _ЛР_ 1_2 _a_b_ __"),
        ("C:\\Users\\отчёт", "C__Users_отчёт"),
        ("Отчёт. . .", "Отчёт"),
        ("  .скрытый  ", "скрытый"),
        ("два   пробела\tи таб", "два пробела_и таб"),
        ("нулевой\u200bширины", "нулевой_ширины"),
        ("con", "con_"),
        ("NUL.tar", "NUL_.tar"),
        ("LPT9", "LPT9_"),
        ("CONSOLE", "CONSOLE"),
        ("", "Отчёт"),
        ("...", "Отчёт"),
    ],
)
def test_safe_filename(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected


def test_safe_filename_limits_length_and_bytes() -> None:
    assert safe_filename("я" * 150) == "я" * 100
    # Эмодзи — 4 байта в UTF-8: 100 символов — это уже 400 байт.
    emoji = safe_filename("😀" * 100)
    assert len(emoji.encode()) <= 200
    assert emoji == "😀" * 50
    # Обрезка не оставляет точку или пробел в конце.
    assert safe_filename("а" * 99 + " б") == "а" * 99


def test_content_disposition_inline_and_attachment() -> None:
    name = "ЛР3_Чистяков.pdf"
    encoded = "%D0%9B%D0%A03_%D0%A7%D0%B8%D1%81%D1%82%D1%8F%D0%BA%D0%BE%D0%B2.pdf"

    assert content_disposition(name) == (
        f"inline; filename=\"__3_________.pdf\"; filename*=UTF-8''{encoded}"
    )
    assert content_disposition("report.zip", attachment=True) == (
        "attachment; filename=\"report.zip\"; filename*=UTF-8''report.zip"
    )


def test_content_disposition_fallback_has_no_quotes_or_percent() -> None:
    header = content_disposition('a"b\\c%41.pdf')

    assert header.startswith('inline; filename="a_b_c_41.pdf"; ')
    assert header.endswith("filename*=UTF-8''a%22b%5Cc%2541.pdf")
