"""Проверки файлов и сверки с материалами на примерах из docs/checks.md: file-missing,
code-not-in-materials, number-not-in-materials."""

from dataclasses import replace

import pytest

from app.modules.checks.context import MaterialSource
from tests.checks_samples import MATERIALS, places, run, snapshot

PROGRESS = "sections/progress.tex"


def progress(text: str) -> dict[str, str]:
    return {PROGRESS: text}


FILE_MISSING = r"""\section{Ход работы}
Окно программы показано на рисунке~\ref{fig:run}, схема — на рисунке~\ref{fig:schema}.
\bbtScreenshot{materials/result.png}{Окно программы}{fig:run}
\bbtScreenshot{materials/metod.pdf}{Схема алгоритма}{fig:schema}
Код приведён в листинге~\ref{lst:main}.
\bbtCodeFile[python]{materials/Main.py}{Программа поиска}{lst:main}
"""


def test_file_missing_example() -> None:
    found = run("file-missing", progress(FILE_MISSING))

    assert places(found) == [(PROGRESS, 3), (PROGRESS, 4), (PROGRESS, 6)]
    assert [finding.message for finding in found] == [
        "Файла materials/result.png нет в проекте — PDF не соберётся. Если это ваш скриншот "
        "или код, загрузите его в материалы. Если ИИ ошибся в имени, попросите выбрать файл "
        "из материалов.",
        "materials/metod.pdf нельзя вставить в отчёт: PDF и документы из материалов читает "
        "только ИИ. Сохраните картинку как PNG или JPG и загрузите её.",
        "Файла materials/Main.py нет в проекте — PDF не соберётся. Если это ваш скриншот или "
        "код, загрузите его в материалы. Если ИИ ошибся в имени, попросите выбрать файл из "
        "материалов. Похожий файл: materials/main.py.",
    ]
    assert {finding.level for finding in found} == {"error"}


def test_file_missing_svg() -> None:
    text = "\\section{Ход работы}\n\\includegraphics{figures/schema.svg}\n"
    project = snapshot(progress(text), binary=("figures/schema.svg",))

    [finding] = run("file-missing", project=project)

    assert finding.message == (
        "Картинки SVG не вставляются. Сохраните figures/schema.svg как PNG и загрузите."
    )


@pytest.mark.parametrize(
    "line",
    [
        "\\bbtScreenshot{materials/run.png}{Окно}{fig:a}",
        "\\bbtScreenshot{materials/run}{Окно}{fig:a}",
        "\\bbtScreenshot{materials/окно программы_1.png}{Окно}{fig:a}",
        "\\includegraphics{figures/plot.pdf}",
        "\\lstinputlisting{materials/main.py}",
    ],
)
def test_file_missing_does_not_fire(line: str) -> None:
    binary = ("materials/run.png", "materials/окно программы_1.png", "figures/plot.pdf")
    project = snapshot(progress(f"\\section{{Ход работы}}\n{line}\n"), binary=binary)

    assert run("file-missing", project=project) == []


CODE = r"""\section{Ход работы}
Программа выводит результат, приведённый в листинге~\ref{lst:out}.
\begin{bbtcode}{text}{Вывод программы}{lst:out}
Линейный поиск: индекс 7, 0.0042 с
Бинарный поиск: индекс 7, 0.0015 с
Сравнений: 4
\end{bbtcode}
"""


def test_code_not_in_materials_example() -> None:
    [finding] = run("code-not-in-materials", progress(CODE))

    assert (finding.file, finding.line, finding.level) == (PROGRESS, 5, "warning")
    assert finding.message == (
        "2 из 3 строк листинга «Вывод программы» нет в ваших материалах, например «Бинарный "
        "поиск: индекс 7, 0.0015 с». Если это вывод программы или ваш код, ИИ мог его "
        "придумать: сверьте с настоящим и загрузите его в материалы — файлом или скриншотом."
    )


def test_code_not_in_materials_does_not_fire() -> None:
    fragment = (
        "\\begin{bbtcode}{python}{Линейный поиск}{lst:linear}\n"
        "def linear_search(items, target):\n"
        "  for index, value in enumerate(items):\n"
        "      if value == target:\n"
        "\t\treturn index\n"
        "  }\n"
        "  # ...\n"
        "  return -1\n"
        "\\end{bbtcode}"
    )
    text = (
        "\\section{Ход работы}\n"
        "\\bbtCodeFile[python]{materials/main.py}{Программа}{lst:main}\n"
        f"{fragment}\n"
    )

    assert run("code-not-in-materials", progress(text)) == []


def test_code_file_outside_materials_is_checked() -> None:
    text = "\\section{Ход работы}\n\\bbtCodeFile[python]{code/fast.py}{Быстрый поиск}{lst:f}\n"
    changes = {PROGRESS: text, "code/fast.py": "def fast_search(items):\n    return 42\n"}

    [finding] = run("code-not-in-materials", changes)

    assert (finding.file, finding.line) == ("code/fast.py", 1)
    assert finding.message.startswith("2 из 2 строк листинга «Быстрый поиск»")


def test_code_check_is_incomplete_while_materials_are_read() -> None:
    materials = (
        *MATERIALS,
        MaterialSource("materials/run2.png", "pending", None, None),
        MaterialSource("materials/task.docx", "failed", None, None),
    )
    project = snapshot(progress(CODE), materials=materials)

    [finding] = run("code-not-in-materials", project=project)

    assert finding.message.endswith(
        " Сверка неполная: не прочитаны materials/run2.png, materials/task.docx."
    )


NUMBERS = r"""\section{Ход работы}
Время поиска приведено в таблице~\ref{tab:time}. Работа выполнена по варианту 12.
\begin{bbttable}{Время поиска, с}{tab:time}
  \begin{tabular}{|r|c|c|}
    \hline
    Длина массива & Линейный & Бинарный \\ \hline
    1000  & 0,0042 & 0,0038 \\ \hline
    10000 & 0,0410 & 0,0035 \\ \hline
  \end{tabular}
\end{bbttable}
Бинарный поиск выполнил 14 сравнений.
"""


def test_number_not_in_materials_example() -> None:
    found = run("number-not-in-materials", progress(NUMBERS))

    assert places(found) == [(PROGRESS, 8), (PROGRESS, 11)]
    assert [finding.message for finding in found] == [
        "Чисел 0,0035 нет в ваших материалах. Если это результаты, ИИ мог их придумать или "
        "посчитать сам: сверьте с выводом программы и скриншотами.",
        "Чисел 14 нет в ваших материалах. Если это результаты, ИИ мог их придумать или "
        "посчитать сам: сверьте с выводом программы и скриншотами.",
    ]


@pytest.mark.parametrize(
    "line",
    [
        "Работа выполнена по варианту 12.",
        "Время — 0,0410 с на 1000 и 10000 элементах.",
        "\\begin{tabular}{|r|c|c|}\n1 & 2 \\\\\n\\end{tabular}",
        "\\bbtScreenshot[0.6\\linewidth]{materials/run.png}{Окно}{fig:a}",
        "Сложность $O(\\log_2 n)$ и \\(n^{42}\\), а также \\[ x = 128 \\]",
        "Выполнены 3 пункта.",
        "Процессор x86, тип int32, файл run_2048.",
        "Массив из 10~000 элементов, то есть 10\\,000.",
        "\\begin{equation}\nT = 512 n\n\\end{equation}",
        "\\begin{bbtcode}{text}{Вывод}{lst:o}\nиндекс 777\n\\end{bbtcode}",
        "Алгоритм описан в методичке~\\cite[с.~55]{metod}.",
    ],
)
def test_number_not_in_materials_does_not_fire(line: str) -> None:
    text = f"\\section{{Ход работы}}\n{line}\n"

    assert run("number-not-in-materials", progress(text)) == []


def test_numbers_in_bibliography_are_not_checked() -> None:
    main = (
        snapshot()
        .texts["main.tex"]
        .replace(
            "\\end{document}",
            "\\begin{thebibliography}{9}\n\\bibitem{knuth} Кнут Д. Т. 3. 1998. 832 с.\n"
            "\\end{thebibliography}\n\\end{document}",
        )
    )

    assert run("number-not-in-materials", {"main.tex": main}) == []


def test_number_forms() -> None:
    text = (
        "\\section{Ход работы}\nВерсия 3.12.1, адрес 192.168.0.1, время 0,00420 с, "
        "10\\,000 и 25~000 элементов.\n"
    )
    materials = (*MATERIALS, MaterialSource("materials/env.txt", "ready", "Python 3.12.1", None))
    project = replace(snapshot(progress(text)), materials=materials)

    [finding] = run("number-not-in-materials", project=project)

    # 0,00420 = 0.0042, 10 000 — из вывода; 3.12.1 — из материала; остальных нет.
    assert finding.message.startswith("Чисел 192.168.0.1; 25 000 нет в ваших материалах.")


def test_number_check_is_incomplete_while_materials_are_read() -> None:
    materials = (*MATERIALS, MaterialSource("materials/out2.txt", "pending", None, None))
    project = snapshot(progress(NUMBERS), materials=materials)

    found = run("number-not-in-materials", project=project)

    assert all(
        finding.message.endswith(" Сверка неполная: не прочитаны materials/out2.txt.")
        for finding in found
    )
    assert places(found) == [(PROGRESS, 8), (PROGRESS, 11)]
