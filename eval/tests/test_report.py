"""Проверки отчёта на вымышленных результатах."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "eval_report", Path(__file__).parents[1] / "report.py"
)
assert spec is not None and spec.loader is not None
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def test_unknowns_do_not_become_zero_or_success() -> None:
    text = report.render_report(
        {"case_id": "synthetic", "run_status": "failed", "cost": None},
        {"expected": {"sections": ["Цель"], "facts": ["Результат 42"]}},
    )
    assert "| Стоимость | недоступно |" in text
    assert "| PDF скачан | недоступно |" in text
    assert "| Итерации исправления | недоступно |" in text
    assert "| Обязательный раздел: Цель | не проверено |" in text
    assert "| Факт: Результат 42 | не проверено |" in text


def test_known_values_and_manual_checklist_are_preserved() -> None:
    text = report.render_report(
        {
            "case_id": "test|1",
            "run_status": "done",
            "build_status": "ok",
            "pdf_downloaded": True,
            "tokens_in": 0,
            "tokens_out": 12,
            "compile_calls": 1,
        },
        {"expected": {"progress": [{"item": "Код", "must": ["Листинг"]}], "must_not": ["Выдумка"]}},
    )
    assert "| Кейс | test\\|1 |" in text
    assert "| PDF скачан | да |" in text
    assert "| Входные токены | 0 |" in text
    assert "| Вызовы compile | 1 |" in text
    assert "| Код: Листинг | не проверено |" in text
    assert "| Не допускать: Выдумка | не проверено |" in text


def test_invalid_checklist_does_not_silently_pass() -> None:
    with pytest.raises(ValueError, match="sections"):
        report.render_report({}, {"expected": {"sections": "Цель"}})


def test_section_file_evidence_is_not_conflated_with_content() -> None:
    text = report.render_report(
        {"section_files": {"Цель": True, "Вывод": False, "Иное": None}},
        {"expected": {"sections": ["Цель", "Вывод", "Иное"]}},
    )
    assert "| Обязательный раздел: Цель | файл есть; содержимое не проверено |" in text
    assert "| Обязательный раздел: Вывод | файл отсутствует |" in text
    assert "| Обязательный раздел: Иное | не проверено |" in text


def test_overview_preserves_partial_results_per_case() -> None:
    text = report.render_overview(
        [
            {
                "case_id": "a",
                "run_status": "done",
                "tokens_in": 0,
                "pdf_downloaded": True,
                "section_files": {"Цель": True},
            },
            {"case_id": "b", "run_status": "failed", "error": "run_timeout"},
        ]
    )
    assert "| a | done | недоступно | да | файлы есть | 0 | недоступно |" in text
    assert "| b | failed | недоступно | недоступно | не проверено | недоступно |" in text
    assert "run_timeout" in text


def test_null_error_is_none_and_missing_error_is_unknown() -> None:
    assert "| Ошибка | нет |" in report.render_report({"error": None}, {})
    assert "| Ошибка | недоступно |" in report.render_report({}, {})
    text = report.render_overview([{"case_id": "a", "error": None}, {"case_id": "b"}])
    lines = text.splitlines()
    assert any(line.startswith("| a |") and line.endswith("| нет |") for line in lines)
    assert any(line.startswith("| b |") and line.endswith("| недоступно |") for line in lines)
