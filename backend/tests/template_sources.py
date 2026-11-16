"""Исходники шаблона, которые реестр при старте не проверяет (T1.4, docs/templates.md).

- Каждый файл раздела подключён в главный файл через \\input. Разбор подключений — тот же,
  что у проверок отчёта (docs/checks.md, «Как читается отчёт»). Раздел без \\input ИИ заполнит,
  а в PDF его не будет.
- meta.sample.tex задаёт ровно те макросы, что бэкенд создаст в meta.tex студента, и только
  командами \\def\\bbt…{…}. Иначе check-template собирает шаблон не так, как сборка у студента:
  макрос, которого бэкенд не создаст, у студента даёт Undefined control sequence.

Проблемы — строками «папка/файл: что не так», как у реестра («Ошибка в шаблоне»).
"""

import re
import uuid
from pathlib import Path

from app.modules.builds.log_parser import uncomment
from app.modules.checks.report import group, read_report
from app.modules.profiles.models import Profile
from app.modules.templates.manifest import TemplateManifest
from app.modules.templates.meta import render_meta
from app.modules.templates.registry import SAMPLE_META, Template

# \def\bbtLabNumber — имя после \bbt; дальше значение в фигурных скобках.
_DEFINITION = re.compile(r"\\def\\bbt([A-Za-z]+)(?![A-Za-z])")


def source_problems(folder: Path, template: Template) -> list[str]:
    """Проблемы исходников шаблона из папки folder: разделы и meta.sample.tex."""
    sample = folder / SAMPLE_META
    text = sample.read_text(encoding="utf-8") if sample.is_file() else None
    where = f"{folder.name}/{SAMPLE_META}"
    return section_problems(folder.name, template) + sample_meta_problems(
        where, template.manifest, text
    )


def section_problems(slug: str, template: Template) -> list[str]:
    """Разделы, файлы которых не подключены в главный файл, — и через другие файлы тоже."""
    manifest = template.manifest
    included = set(read_report(manifest.main, template.files).files)
    return [
        f"{slug}/{manifest.main}: sections.{index}.file: {section.file} не подключён через "
        f"\\input — раздела «{section.title}» не будет в PDF"
        for index, section in enumerate(manifest.sections)
        if section.file not in included
    ]


def backend_macros(manifest: TemplateManifest) -> list[str]:
    """Макросы meta.tex, который бэкенд создаст по шаблону: имена после \\bbt."""
    empty = dict.fromkeys(
        ("last_name", "first_name", "middle_name", "group_name", "faculty", "department"), ""
    )
    meta = render_meta(Profile(user_id=uuid.uuid4(), **empty), manifest, {})
    return _DEFINITION.findall(meta)


def sample_meta_problems(where: str, manifest: TemplateManifest, text: str | None) -> list[str]:
    """Расхождения meta.sample.tex (текст text, None — файла нет) с meta.tex от бэкенда."""
    if text is None:
        return [f"{where}: нет файла — без него check-template не соберёт шаблон"]
    names, bad_lines = _definitions(text)
    problems = [
        f"{where}: строка {line}: в meta.tex бэкенд пишет только \\def\\bbt…{{…}} — "
        "остального у студента не будет"
        for line in bad_lines
    ]
    expected = backend_macros(manifest)
    for name in sorted({name for name in names if names.count(name) > 1}):
        problems.append(f"{where}: \\bbt{name} задан дважды")
    for name in sorted(set(names) - set(expected)):
        problems.append(
            f"{where}: \\bbt{name} бэкенд не создаст — такого поля в template.yaml нет. "
            "Если шаблон его использует, у студента сборка упадёт"
        )
    for name in sorted(set(expected) - set(names)):
        problems.append(
            f"{where}: нет \\bbt{name} — бэкенд его создаст, а check-template без него "
            "собирает шаблон не так, как у студента"
        )
    return problems


def _definitions(text: str) -> tuple[list[str], list[int]]:
    """Имена из \\def\\bbt…{…} по порядку и номера строк, где стоит что-то другое.

    Значение поля type: text бывает в несколько строк, поэтому файл читается командами,
    а не строками. Комментарии убраны так же, как в разборе лога сборки. После строки не по
    формату разбор идёт со следующей строки: остальные макросы не теряются.
    """
    # BOM в начале файла (так сохраняет Блокнот Windows) XeTeX пропускает — и здесь тоже.
    code = "\n".join(uncomment(line) for line in text.removeprefix("﻿").splitlines())
    names: list[str] = []
    bad_lines: list[int] = []
    position = _skip_space(code, 0)
    while position < len(code):
        match = _DEFINITION.match(code, position)
        value = group(code, match.end()) if match else None
        if match is None or value is None:
            bad_lines.append(code.count("\n", 0, position) + 1)
            end_of_line = code.find("\n", position)
            position = len(code) if end_of_line == -1 else _skip_space(code, end_of_line)
            continue
        names.append(match[1])
        # value — содержимое без скобок: закрывающая скобка стоит на value.end.
        position = _skip_space(code, value.end + 1)
    return names, bad_lines


def _skip_space(code: str, position: int) -> int:
    while position < len(code) and code[position].isspace():
        position += 1
    return position
