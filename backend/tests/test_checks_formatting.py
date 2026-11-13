"""Проверки оформления текста на примерах из docs/checks.md: heading-format, list-format,
formula-format, bib-order, manual-formatting."""

import pytest

from tests.checks_samples import lab_files, places, run

PROGRESS = "sections/progress.tex"
CONCLUSION = "sections/conclusion.tex"


def test_heading_format_example() -> None:
    text = (
        "\\section{Ход работы}\n\\subsection{линейный поиск.}\n"
        "Поиск реализован в функции \\texttt{linear\\_search}.\n\\paragraph{Замеры}\n"
        "Время поиска измерено на массиве из 1000 элементов.\n"
    )

    found = run("heading-format", {PROGRESS: text})

    assert places(found) == [(PROGRESS, 2), (PROGRESS, 4)]
    assert [finding.message for finding in found] == [
        "Заголовок «линейный поиск.»: начните с прописной буквы, уберите точку в конце.",
        "Заголовок «Замеры» — четвёртый уровень, а по правилам их не больше трёх (3.1.2). "
        "Попросите ИИ сделать его подразделом или обычным абзацем.",
    ]
    assert {finding.level for finding in found} == {"warning"}


@pytest.mark.parametrize(
    "heading",
    [
        "\\subsection{Функция main()}",
        "\\subsection{pandas и NumPy}",
        "\\subsection*{Замеры...}",
        "\\subsubsection[Кратко]{Подробно о поиске}",
    ],
)
def test_heading_format_does_not_fire(heading: str) -> None:
    assert run("heading-format", {PROGRESS: f"\\section{{Ход работы}}\n{heading}\n"}) == []


LIST = r"""\section{Выводы}
В ходе работы:
\begin{itemize}
  \item Реализованы линейный и бинарный поиск.
  \item измерено время поиска
  \item бинарный поиск оказался быстрее;
\end{itemize}
"""


def test_list_format_example() -> None:
    found = run("list-format", {CONCLUSION: LIST})

    assert places(found) == [(CONCLUSION, 4), (CONCLUSION, 5), (CONCLUSION, 6)]
    assert [finding.message for finding in found] == [
        "Пункт «Реализованы линейный и бинарный поиск.»: начните со строчной буквы, "
        "поставьте «;» в конце.",
        "Пункт «измерено время поиска»: поставьте «;» в конце.",
        "Пункт «бинарный поиск оказался быстрее;»: поставьте «.» в конце — это последний пункт.",
    ]


def test_list_format_does_not_fire() -> None:
    text = (
        "\\section{Выводы}\n\\begin{enumerate}\n  \\item SQL-запрос выбирает заказы;\n"
        "  \\item СУБД хранит данные;\n  \\item сравнены методы:\n  \\begin{enumerate}\n"
        "    \\item линейный~\\ref{lst:a};\n    \\item бинарный $O(\\log n)$;\n"
        "  \\end{enumerate}\n  \\item сделаны выводы.\n\\end{enumerate}\n"
    )

    assert run("list-format", {CONCLUSION: text}) == []


def test_list_format_last_item_of_nested_list() -> None:
    text = (
        "\\section{Выводы}\n\\begin{itemize}\n\\item сравнены методы:\n\\begin{itemize}\n"
        "\\item линейный;\n\\item бинарный;\n\\end{itemize}\n\\end{itemize}\n"
    )

    found = run("list-format", {CONCLUSION: text})

    assert places(found) == [(CONCLUSION, 6)]


FORMULA = r"""\section{Ход работы}
Время поиска оценивается по формуле~\eqref{eq:time}.
\begin{equation}\label{eq:time}
  T(n) = c \cdot \log_2 n,
\end{equation}

где: $T(n)$ – время поиска, с;\\
$c$ – постоянная, зависящая от компьютера.
"""


def test_formula_format_example() -> None:
    [finding] = run("formula-format", {PROGRESS: FORMULA})

    assert (finding.file, finding.line, finding.level) == (PROGRESS, 7, "warning")
    assert finding.message == (
        "Пояснение к формуле начинают словом «где» — без двоеточия, сразу под формулой, без "
        "пустой строки. Попросите ИИ исправить."
    )


def test_formula_format_capital_and_display_math() -> None:
    text = "\\section{Ход работы}\n\\[ T = c \\]\nГде $c$ – постоянная.\n"

    [finding] = run("formula-format", {PROGRESS: text})

    assert "— со строчной буквы." in finding.message
    assert finding.line == 3


def test_formula_format_does_not_fire() -> None:
    # Пример из templates.md: «где» в следующей строке, без двоеточия.
    text = (
        "\\section{Ход работы}\n\\begin{equation}\\label{eq:t}\n  T = c \\cdot n,\n"
        "\\end{equation}\nгде $T$ – время, с;\\\\\n$c$ – постоянная.\n"
        "\\begin{equation*}\nx = 1\n\\end{equation*}\n%\nгде $x$ — число.\n"
    )

    assert run("formula-format", {PROGRESS: text}) == []


def bibliography(*items: str) -> str:
    entries = "".join(
        f"  \\bibitem{{{key}}} {text}\n" for key, text in zip(items[::2], items[1::2], strict=True)
    )
    return lab_files()["main.tex"].replace(
        "\\end{document}",
        f"\\begin{{thebibliography}}{{9}}\n{entries}\\end{{thebibliography}}\n\\end{{document}}",
    )


GOAL = (
    "\\section{Цель работы}\n"
    "Цель работы — изучить методы поиска элемента в массиве~\\cite{metod}.\n"
)
PYTHON = "\\section{Ход работы}\nПрограмма написана на языке Python~\\cite{python}.\n"


def test_bib_order_example() -> None:
    main = bibliography(
        "python",
        "Документация Python.",
        "metod",
        "Методические указания к лабораторной работе № 2.",
    )

    [finding] = run("bib-order", {"sections/goal.tex": GOAL, PROGRESS: PYTHON, "main.tex": main})

    assert finding.file == "main.tex"
    assert finding.line == main[: main.index("\\bibitem{python}")].count("\n") + 1
    assert finding.message == (
        "Источники должны идти в порядке первой ссылки в тексте. «Документация Python.» стоит "
        "1-м, а сослались на него 2-м. Попросите ИИ переставить источники."
    )


def test_bib_order_does_not_fire() -> None:
    main = bibliography(
        "metod", "Методические указания.", "knuth", "Кнут Д.", "python", "Документация Python."
    )

    assert run("bib-order", {"sections/goal.tex": GOAL, PROGRESS: PYTHON, "main.tex": main}) == []


def test_manual_formatting_example() -> None:
    main = lab_files()["main.tex"].replace(
        "\\documentclass{mtuci-report}\n",
        "\\documentclass{mtuci-report}\n\\usepackage[margin=2cm]{geometry}\n",
    )
    text = (
        "\\section{Ход работы}\n\\newpage\n"
        "\\noindent{\\small Результаты замеров приведены ниже.}\n\\vspace{1cm}\n"
    )

    found = run("manual-formatting", {"main.tex": main, PROGRESS: text})

    usepackage = main.split("\n").index("\\usepackage[margin=2cm]{geometry}") + 1
    assert places(found) == [
        ("main.tex", usepackage),
        (PROGRESS, 2),
        (PROGRESS, 3),
        (PROGRESS, 3),
        (PROGRESS, 4),
    ]
    assert found[0].message == (
        "Подключён пакет «geometry». Оформление задаёт шаблон, пакеты для него не нужны. Если "
        "пакет нужен для формул или особых символов — оставьте его."
    )
    assert found[1].message == (
        "Оформление задано вручную (\\newpage): из-за этого отчёт может разойтись с правилами "
        "по полям, шрифту, отступам или разрывам страниц. Попросите ИИ убрать команду."
    )
    assert ["\\noindent" in found[2].message, "\\small" in found[3].message] == [True, True]


def test_manual_formatting_does_not_fire() -> None:
    text = (
        "\\section{Ход работы}\n% \\newpage\n\\begin{bbtcode}{latex}{Пример}{lst:a}\n"
        "\\vspace{1cm}\n\\end{bbtcode}\nгде $T$ – время;\\\\\n$c$ – постоянная.\n"
    )

    assert run("manual-formatting", {PROGRESS: text}) == []
