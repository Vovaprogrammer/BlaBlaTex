"""Проверки структуры и титула на примерах из docs/checks.md: section-empty, placeholder,
title-empty."""

from dataclasses import replace

import pytest

from tests.checks_samples import lab_files, places, run, snapshot

# Остальные разделы заполнены: в примере пустой только sections/goal.tex.
FILLED = {
    "sections/task.tex": "\\section{Задание}\nРеализовать поиск.\n",
    "sections/progress.tex": "\\section{Ход работы}\nСделано.\n",
    "sections/conclusion.tex": "\\section{Выводы}\nГотово.\n",
}


def test_section_empty_template_file() -> None:
    # Пример 1: sections/goal.tex как в шаблоне.
    found = run("section-empty", FILLED)

    assert places(found) == [("sections/goal.tex", 1)]
    assert found[0].message == (
        "Раздел «Цель работы» пустой. Попросите ИИ заполнить его по материалам. Если ИИ "
        "не нашёл, из чего писать, — загрузите методичку или задание."
    )
    assert (found[0].level, found[0].place) == ("error", "file")


def test_section_missing_from_main() -> None:
    # Пример 2: из main.tex удалена строка \input{sections/task}.
    main = lab_files()["main.tex"].replace("\\input{sections/task}\n", "")

    found = [f for f in run("section-empty", {"main.tex": main}) if "нет в отчёте" in f.message]

    assert places(found) == [("main.tex", None)]
    assert found[0].message == (
        "Раздела «Задание» нет в отчёте: файл sections/task.tex удалён или не подключён. "
        "Попросите ИИ вернуть раздел."
    )


def test_section_file_deleted() -> None:
    found = run("section-empty", {"sections/task.tex": None})

    assert ("main.tex", None) in places(found)


@pytest.mark.parametrize(
    "body",
    [
        "Цель работы — изучить поиск.",
        "\\bbtScreenshot{materials/run.png}{Окно программы}{fig:run}",
        "\\begin{bbtcode}{text}{Вывод}{lst:out}\nx\n\\end{bbtcode}",
        "\\begin{bbttable}{Время}{tab:t}\n\\begin{tabular}{|r|}\n1 \\\\\n\\end{tabular}\n"
        "\\end{bbttable}",
    ],
)
def test_section_with_content_is_not_empty(body: str) -> None:
    found = run("section-empty", {"sections/goal.tex": f"\\section{{Цель работы}}\n{body}\n"})

    assert "sections/goal.tex" not in [finding.file for finding in found]


def test_section_of_only_subheadings_and_labels_is_empty() -> None:
    goal = (
        "\\section{Цель работы}\\label{sec:goal}\n\\subsection*{Цель}\n"
        "\\subsubsection[Кратко]{Подробно}\n% комментарий\n"
    )

    found = run("section-empty", {"sections/goal.tex": goal})

    assert ("sections/goal.tex", 1) in places(found)


def test_optional_section_is_not_checked() -> None:
    project = snapshot()
    sections = tuple(replace(section, required=False) for section in project.sections)

    assert run("section-empty", project=replace(project, sections=sections)) == []


PLACEHOLDER_PROGRESS = r"""\section{Ход работы}
\subsection{Линейный поиск}
TODO: описать алгоритм.
Окно программы показано на рисунке~\ref{fig:run}.
\bbtScreenshot{materials/run.png}{[Вставьте подпись]}{fig:run}
% TODO: сократить раздел
"""


def test_placeholder_example() -> None:
    found = run("placeholder", {"sections/progress.tex": PLACEHOLDER_PROGRESS})

    assert places(found) == [("sections/progress.tex", 3), ("sections/progress.tex", 5)]
    assert [finding.message for finding in found] == [
        "В тексте осталась заглушка «TODO». Замените её настоящим текстом или попросите ИИ "
        "дописать это место по материалам.",
        "В тексте осталась заглушка «[Вставьте подпись]». Замените её настоящим текстом или "
        "попросите ИИ дописать это место по материалам.",
    ]


@pytest.mark.parametrize(
    ("line", "fragment"),
    [
        ("Здесь fixme.", "fixme"),
        ("Срок — TBD.", "TBD"),
        ("Lorem  ipsum dolor sit amet.", "Lorem  ipsum"),
        ("Проверить XXX позже.", "XXX"),
        ("\\lipsum[1]", "\\lipsum"),
        ("\\Blindtext", "\\Blindtext"),
        ("Результат: <здесь вывод программы>.", "<здесь вывод программы>"),
        ("Вариант: [ваш вариант].", "[ваш вариант]"),
        ("Время ??? с.", "???"),
    ],
)
def test_placeholder_kinds(line: str, fragment: str) -> None:
    found = run("placeholder", {"sections/goal.tex": f"\\section{{Цель работы}}\n{line}\n"})

    assert [(finding.line, finding.message.split("«")[1].split("»")[0]) for finding in found] == [
        (2, fragment)
    ]


@pytest.mark.parametrize(
    "line",
    [
        "% TODO: сократить раздел",
        "Нужно вставить элемент в дерево.",
        "Алгоритм описан в методичке~\\cite[с.~5]{metod}.",
        "\\bbtScreenshot[0.6\\linewidth]{materials/run.png}{Окно}{fig:run}",
        "Нужен [указатель на начало] и [добавление в конец].",
        "Проверка xxx и todolist не заглушки.",
        "Вопрос?? Ответ.",
        "\\begin{bbtcode}{python}{Код}{lst:code}\n# TODO: ускорить\n\\end{bbtcode}",
    ],
)
def test_placeholder_does_not_fire(line: str) -> None:
    found = run("placeholder", {"sections/goal.tex": f"\\section{{Цель работы}}\n{line}\n"})

    assert found == []


def test_placeholder_in_code_file_is_not_checked() -> None:
    project_files = {"materials/main.py": "# TODO: ускорить\nprint(1)\n"}

    assert run("placeholder", project_files) == []


def test_placeholder_in_table_cell() -> None:
    table = (
        "\\section{Цель работы}\n\\begin{bbttable}{Время}{tab:t}\n\\begin{tabular}{|r|c|}\n"
        "1000 & TODO \\\\\n\\end{tabular}\n\\end{bbttable}\n"
    )

    assert places(run("placeholder", {"sections/goal.tex": table})) == [("sections/goal.tex", 4)]


def test_title_empty_example() -> None:
    meta = lab_files()["meta.tex"]
    meta = meta.replace("\\def\\bbtGroup{БВТ0000}", "\\def\\bbtGroup{}")
    meta = meta.replace("\\def\\bbtTeacher{доц. Петров П. П.}", "\\def\\bbtTeacher{}")

    found = run("title-empty", {"meta.tex": meta})

    assert [(f.place, f.field, f.file, f.line) for f in found] == [
        ("profile", "group_name", None, None),
        ("fields", "teacher", None, None),
    ]
    assert [finding.message for finding in found] == [
        "На титульном листе нет группы. Заполните это в профиле — титульник обновится сам.",
        "На титульном листе нет поля «Преподаватель». Заполните его в полях работы — например, "
        "преподаватель «доц. Петров П. П.».",
    ]
    assert {finding.level for finding in found} == {"warning"}


def test_title_empty_field_without_example() -> None:
    meta = lab_files()["meta.tex"].replace("\\def\\bbtLabNumber{2}", "\\def\\bbtLabNumber{}")

    [finding] = run("title-empty", {"meta.tex": meta})

    assert finding.message == (
        "На титульном листе нет поля «Номер работы». Заполните его в полях работы."
    )
    assert finding.field == "lab_number"


def test_title_empty_does_not_fire() -> None:
    meta = lab_files()["meta.tex"].replace("\\def\\bbtVariant{12}", "\\def\\bbtVariant{}")
    without_title = lab_files()["main.tex"].replace("\\bbtTitlePage\n", "")
    empty_meta = lab_files()["meta.tex"].replace("\\def\\bbtGroup{БВТ0000}", "\\def\\bbtGroup{}")

    assert run("title-empty", {"meta.tex": meta}) == []
    assert run("title-empty", {"main.tex": without_title, "meta.tex": empty_meta}) == []
