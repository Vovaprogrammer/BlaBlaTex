"""Отчёт eval: неизвестное не подменяется успешной проверкой."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any  # JSON и YAML кейса содержат вложенные значения разных типов.

import yaml


def _cell(value: object) -> str:
    if value is None:
        return "недоступно"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_overview(results: list[dict[str, Any]]) -> str:
    """Сводит результаты разных кейсов без суммирования неизвестных величин."""
    lines = [
        "# Сводка eval",
        "",
        "| Кейс | Прогон | Сборка | PDF | Файлы разделов | Вход | Выход | Стоимость | Ошибка |",
        "|---|---|---|---|---|---:|---:|---|---|",
    ]
    for result in results:
        pdf = {True: "да", False: "нет"}.get(result.get("pdf_downloaded"))
        sections = result.get("section_files")
        presence = "не проверено"
        if isinstance(sections, dict) and sections:
            values = list(sections.values())
            if any(value is False for value in values):
                presence = "есть отсутствующие"
            elif all(value is True for value in values):
                presence = "файлы есть"
        values = (
            result.get("case_id"),
            result.get("run_status"),
            result.get("build_status"),
            pdf,
            presence,
            result.get("tokens_in"),
            result.get("tokens_out"),
            result.get("cost"),
            result.get("error"),
        )
        lines.append("| " + " | ".join(_cell(value) for value in values) + " |")
    lines.extend(["", "Наличие файлов не подтверждает заполненность или включение разделов в PDF."])
    return "\n".join(lines) + "\n"


def render_report(result: dict[str, Any], case: dict[str, Any]) -> str:
    """Создаёт отчёт по фактическим данным прогона и ручному чек-листу."""
    expected = case.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError("expected должен быть объектом")
    section_files = result.get("section_files") or {}
    if not isinstance(section_files, dict):
        raise ValueError("section_files должен быть объектом")
    lines = [
        "# Результат eval",
        "",
        "| Показатель | Значение |",
        "|---|---|",
        f"| Кейс | {_cell(result.get('case_id'))} |",
        f"| Статус прогона | {_cell(result.get('run_status'))} |",
        f"| Статус сборки | {_cell(result.get('build_status'))} |",
        f"| PDF скачан | {_cell({True: 'да', False: 'нет'}.get(result.get('pdf_downloaded')))} |",
        f"| Входные токены | {_cell(result.get('tokens_in'))} |",
        f"| Выходные токены | {_cell(result.get('tokens_out'))} |",
        f"| Стоимость | {_cell(result.get('cost'))} |",
        f"| Вызовы compile | {_cell(result.get('compile_calls'))} |",
        "| Итерации исправления | недоступно |",
        f"| Ошибка | {_cell(result.get('error'))} |",
        "",
        "Вызовы compile не равны числу исправлений. Чек-лист требует ручной проверки: "
        "наличие файла не подтверждает его заполненность или включение в PDF.",
        "",
        "| Критерий | Проверка |",
        "|---|---|",
    ]
    for label, key in (
        ("Обязательный раздел", "sections"),
        ("Факт", "facts"),
        ("Не допускать", "must_not"),
    ):
        items = expected.get(key) or []
        if not isinstance(items, list):
            raise ValueError(f"expected.{key} должен быть списком")
        for item in items:
            check = "не проверено"
            if key == "sections" and isinstance(item, str):
                if section_files.get(item) is True:
                    check = "файл есть; содержимое не проверено"
                elif section_files.get(item) is False:
                    check = "файл отсутствует"
            lines.append(f"| {label}: {_cell(item)} | {check} |")
    progress = expected.get("progress") or []
    if not isinstance(progress, list):
        raise ValueError("expected.progress должен быть списком")
    for section in progress:
        if not isinstance(section, dict) or not isinstance(section.get("must", []), list):
            raise ValueError("Пункт expected.progress должен содержать список must")
        for item in section.get("must", []):
            lines.append(f"| {_cell(section.get('item'))}: {_cell(item)} | не проверено |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать Markdown-отчёт eval")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--result", type=Path)
    source.add_argument("--results-dir", type=Path)
    parser.add_argument("--case", type=Path)
    args = parser.parse_args()
    if args.results_dir is not None:
        if args.case is not None:
            parser.error("--case используется с одним --result")
        paths = sorted(args.results_dir.glob("*.json"))
        if not paths:
            parser.error("Нет JSON-результатов")
        try:
            results = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        except (OSError, UnicodeError, json.JSONDecodeError):
            parser.error("Не удалось прочитать результаты")
        if not all(isinstance(item, dict) for item in results):
            parser.error("Каждый результат должен быть объектом")
        sys.stdout.write(render_overview(results))
        return
    if args.case is None:
        parser.error("Для --result требуется --case")
    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
        case = yaml.safe_load(args.case.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError):
        parser.error("Не удалось прочитать результат или кейс")
    if not isinstance(result, dict) or not isinstance(case, dict):
        parser.error("Результат и кейс должны быть объектами")
    sys.stdout.write(render_report(result, case))


if __name__ == "__main__":
    main()
