"""Как проверки читают отчёт (docs/checks.md, «Как читается отчёт») и в каком порядке
отдают находки (architecture.md 9.4)."""

import time
from dataclasses import replace

from app.modules.checks.context import MaterialSource
from app.modules.checks.engine import check_project
from app.modules.checks.report import read_report
from app.modules.checks.schemas import CHECK_IDS, PDF_CHECKS
from tests.checks_samples import MANIFEST, lab_files, run, snapshot

SOURCE_CHECKS = set(CHECK_IDS) - PDF_CHECKS


def report_of(files: dict[str, str]) -> list[str]:
    return read_report("main.tex", files).files


def test_report_files_in_order_of_inclusion() -> None:
    files = {
        "main.tex": "\\input{meta}\n\\begin{document}\n\\input{a}\\include{./parts/b.tex}\n"
        "\\input{missing}\n\\end{document}\n",
        "meta.tex": "\\def\\bbtGroup{}\n",
        "a.tex": "\\input{parts/c}\n",
        "parts/b.tex": "Б\n\\input{a}\n",
        "parts/c.tex": "\\input{a}\nВ\n",
        "loose.tex": "Никуда не подключён.\n",
    }

    # meta.tex как текст не читается; повторное подключение по кругу — нет.
    assert report_of(files) == ["main.tex", "a.tex", "parts/c.tex", "parts/b.tex"]


def test_unconnected_file_is_not_checked() -> None:
    assert run("placeholder", {"sections/extra.tex": "TODO\n"}) == []


def test_comments_and_escaped_percent() -> None:
    goal = (
        "\\section{Цель работы}\nРост на 50\\% TODO\n"
        "Перевод строки\\\\% TODO в комментарии\n"
        "\\begin{bbtcode}{text}{Вывод}{lst:o}\nЗагрузка 100% TODO\n\\end{bbtcode}\n"
    )

    found = run("placeholder", {"sections/goal.tex": goal})

    assert [finding.line for finding in found] == [2]


def test_positions_map_to_file_and_line() -> None:
    files = lab_files()
    files["sections/goal.tex"] = "\\section{Цель работы}\n\nОкно~\\ref{fig:a} и \\cite{a,b}.\n"
    report = read_report("main.tex", files)

    refs = [(ref.kind, ref.key, report.locate(ref.start)) for ref in report.refs]

    assert refs == [
        ("label", "fig:a", ("sections/goal.tex", 3)),
        ("cite", "a", ("sections/goal.tex", 3)),
        ("cite", "b", ("sections/goal.tex", 3)),
    ]
    assert refs[1:] == sorted(refs[1:], key=lambda item: item[1])


def test_appendix_splits_main_part() -> None:
    files = lab_files()
    files["main.tex"] = files["main.tex"].replace(
        "\\end{document}",
        "\\appendix\n\\section{Программа поиска}\n\\label{app:code}\n\\end{document}",
    )
    report = read_report("main.tex", files)

    [appendix] = [element for element in report.elements if element.kind == "appendix"]

    assert report.show(appendix.caption) == "Программа поиска" if appendix.caption else False
    assert appendix.label == "app:code"
    assert report.in_appendix(appendix.start)


def test_plain_text_keeps_captions_and_cells_but_not_commands() -> None:
    files = lab_files()
    files["sections/goal.tex"] = (
        "\\section{Цель работы}\n\\bbtScreenshot[0.6\\linewidth]{materials/run.png}{Окно}{fig:a}\n"
        "\\begin{bbttable}{Время}{tab:t}\n\\begin{tabular}{|r|c|}\n1000 & 0,0042 \\\\\n"
        "\\end{tabular}\n\\end{bbttable}\n\\textbf{Жирный} и \\texttt{linear\\_search}.\n"
    )
    report = read_report("main.tex", files)

    words = report.show(report.body).split()

    assert words == [
        "Цель", "работы", "Окно", "Время", "1000", "0,0042", "Жирный", "и", "linear_search.",
        "Задание", "Ход", "работы", "Выводы",
    ]  # fmt: skip


def test_findings_order_and_determinism() -> None:
    goal = "\\section{Цель работы}\nTODO и \\vspace{1cm} TODO\n"
    meta = lab_files()["meta.tex"].replace("\\def\\bbtGroup{БВТ0000}", "\\def\\bbtGroup{}")
    project = snapshot({"sections/goal.tex": goal, "meta.tex": meta})

    first = check_project(project, set(CHECK_IDS), None)
    second = check_project(project, set(CHECK_IDS), None)

    assert first == second
    order = [(finding.check, finding.file, finding.line) for finding in first]
    assert order == [
        ("title-empty", None, None),
        ("placeholder", "sections/goal.tex", 2),
        ("manual-formatting", "sections/goal.tex", 2),
        ("placeholder", "sections/goal.tex", 2),
        ("section-empty", "sections/task.tex", 1),
        ("section-empty", "sections/progress.tex", 1),
        ("section-empty", "sections/conclusion.tex", 1),
    ]


def test_only_listed_checks_run() -> None:
    project = snapshot()

    assert check_project(project, set(), None) == []
    assert {f.check for f in check_project(project, {"section-empty"}, None)} == {"section-empty"}


def test_template_lists_all_checks() -> None:
    assert MANIFEST.checks == list(CHECK_IDS)


def thesis() -> dict[str, str]:
    """Синтетическая ВКР примерно на 100 страниц: 10 глав по 10 подразделов, рисунки,
    таблицы, листинги, формулы, перечисления и 100 источников."""
    files = lab_files()
    chapters = []
    for chapter in range(1, 11):
        parts = [f"\\section{{Глава {chapter}}}\n"]
        for part in range(1, 11):
            key = f"{chapter}-{part}"
            sentence = (
                f"Текст главы с числом 1000, ссылкой на источник~\\cite{{s{key}}} и словами. "
            )
            parts.append(
                f"\\subsection{{Подраздел {key}}}\n"
                + sentence * 35
                + f"\nОкно показано на рисунке~\\ref{{fig:{key}}}.\n"
                f"\\bbtScreenshot{{materials/run.png}}{{Окно {key}}}{{fig:{key}}}\n"
                "\\begin{itemize}\n\\item первый пункт;\n\\item второй пункт.\n\\end{itemize}\n"
                f"По формуле~\\eqref{{eq:{key}}}\n\\begin{{equation}}\\label{{eq:{key}}}\n"
                "T = c \\cdot n,\n\\end{equation}\nгде $T$ — время.\n"
            )
            if part % 3 == 0:
                parts.append(
                    f"Время — в таблице~\\ref{{tab:{key}}}.\n"
                    f"\\begin{{bbttable}}{{Время {key}}}{{tab:{key}}}\n"
                    "\\begin{tabular}{|r|c|}\n"
                    + "1000 & 0,0042 \\\\ \\hline\n" * 10
                    + "\\end{tabular}\n\\end{bbttable}\n"
                )
            if part % 5 == 0:
                code = "\n".join(f"    value = items[{n}]  # шаг {n}" for n in range(30))
                parts.append(
                    f"Код — в листинге~\\ref{{lst:{key}}}.\n"
                    f"\\begin{{bbtcode}}{{python}}{{Код {key}}}{{lst:{key}}}\n{code}\n"
                    "\\end{bbtcode}\n"
                )
        files[f"chapters/{chapter}.tex"] = "".join(parts)
        chapters.append(f"\\input{{chapters/{chapter}}}\n")
    bibliography = "".join(
        f"\\bibitem{{s{c}-{p}}} Источник {c}.{p}.\n" for c in range(1, 11) for p in range(1, 11)
    )
    files["main.tex"] = (
        files["main.tex"]
        .replace(
            "\\input{sections/goal}\n",
            "\\input{sections/goal}\n" + "".join(chapters),
        )
        .replace(
            "\\end{document}",
            f"\\begin{{thebibliography}}{{99}}\n{bibliography}\\end{{thebibliography}}\n\\end{{document}}",
        )
    )
    return files


def test_large_report_is_fast() -> None:
    files = thesis()
    project = snapshot(files)
    methods = MaterialSource("materials/book.pdf", "ready", "Справочник. " * 40_000, None)
    project = replace(project, materials=(*project.materials, methods))
    size = sum(len(text) for text in files.values())

    started = time.perf_counter()
    found = check_project(project, SOURCE_CHECKS, None)
    elapsed = time.perf_counter() - started

    assert size > 250_000
    assert found
    # Ориентир — доли секунды; запас — на медленную машину CI.
    assert elapsed < 5
