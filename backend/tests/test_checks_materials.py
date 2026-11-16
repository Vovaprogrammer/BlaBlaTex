"""Проверки файлов и сверки с материалами на примерах из docs/checks.md: file-missing,
code-not-in-materials, number-not-in-materials."""

from collections.abc import Callable
from dataclasses import replace

import pytest

from app.modules.checks.context import MaterialSource, Snapshot
from app.modules.checks.schemas import CheckFinding
from tests.checks_samples import MAIN_PY, MATERIALS, places, run, snapshot

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


def test_file_missing_notebook_as_code_file() -> None:
    # Ноутбук в сборку не идёт: \bbtCodeFile вставил бы его сырым JSON.
    text = "\\section{Ход работы}\n\\bbtCodeFile{materials/lab.ipynb}{Код}{lst:code}\n"
    project = snapshot(progress(text), binary=("materials/lab.ipynb",))

    [finding] = run("file-missing", project=project)

    assert finding.message == (
        "Ноутбук materials/lab.ipynb нельзя вставить в отчёт файлом: его читает только ИИ. "
        "Попросите ИИ вставить нужные ячейки кода в листинг текстом."
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


def test_code_file_fragment_checks_only_its_lines() -> None:
    code = "def fast_search(items):\n    return 42\n\n\ndef linear_search(items, target):\n"
    text = (
        "\\section{Ход работы}\n"
        "\\bbtCodeFile[python, lines=2-4]{code/fast.py}{Быстрый поиск}{lst:f}\n"
        "\\bbtCodeFile[python, lines=5]{code/fast.py}{Линейный поиск}{lst:l}\n"
    )
    changes = {PROGRESS: text, "code/fast.py": code}

    [finding] = run("code-not-in-materials", changes)

    assert (finding.file, finding.line) == ("code/fast.py", 2)
    assert finding.message.startswith("1 из 1 строк листинга «Быстрый поиск»")


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (
            "80-120",
            "Листинг показывает строки 80–120 файла materials/main.py, но строк в нём всего "
            "85, поэтому фрагмент в PDF обрезан. Возможно, файл изменился после того, как ИИ "
            "выбрал строки: попросите ИИ выбрать их заново.",
        ),
        ("90", "строки 90 файла materials/main.py, но строк в нём всего 85, поэтому фрагмент "),
    ],
)
def test_file_missing_fragment_past_end(lines: str, message: str) -> None:
    text = (
        "\\section{Ход работы}\nКод — в листинге~\\ref{lst:main}.\n"
        f"\\bbtCodeFile[python, lines={lines}]{{materials/main.py}}{{Программа}}{{lst:main}}\n"
    )

    [finding] = run("file-missing", progress(text))

    assert (finding.file, finding.line) == (PROGRESS, 3)
    assert message in finding.message
    assert finding.message.endswith("попросите ИИ выбрать их заново.")
    assert ("пустой" in finding.message) == (lines == "90")


def test_file_missing_fragment_inside_file_does_not_fire() -> None:
    text = (
        "\\section{Ход работы}\n"
        "\\bbtCodeFile[python, lines=80-85]{materials/main.py}{Программа}{lst:main}\n"
    )

    assert run("file-missing", progress(text)) == []


MAIN = "materials/main.py"
# binary_search — строки 19–31 в fixtures/checks/main.py.
BINARY = r"""\section{Ход работы}
\bbtCodeFile[python, lines=19-31]{materials/main.py}{Бинарный поиск}{lst:bin}
"""


def changed_main(edit: Callable[[list[str]], None]) -> str:
    """main.py после правки edit — над списком строк, номера с 0."""
    lines = MAIN_PY.split("\n")
    edit(lines)
    return "\n".join(lines)


def replaced(main_py: str, *, listed: str | None = MAIN_PY) -> Snapshot:
    """Фрагмент BINARY вставили, когда main.py был listed; теперь main.py — main_py.
    listed=None — истории нет."""
    project = snapshot({PROGRESS: BINARY, MAIN: main_py})
    if listed is None:
        return project
    return replace(project, listed_code={(PROGRESS, MAIN, (19, 31)): listed})


def two_imports_on_top(lines: list[str]) -> None:
    lines[8:8] = ["import math", "import os"]


def test_file_missing_shifted_fragment_example() -> None:
    [finding] = run("file-missing", project=replaced(changed_main(two_imports_on_top)))

    assert (finding.file, finding.line, finding.level) == (PROGRESS, 2, "error")
    assert finding.message == (
        "Файл materials/main.py изменился после того, как в отчёт вставили его строки 19–31: "
        "листинг «Бинарный поиск» теперь показывает другие строки. Прежние строки теперь — "
        "21–33. Попросите ИИ выбрать строки заново."
    )


def line_inside(lines: list[str]) -> None:
    lines.insert(23, "        steps += 1")


def first_line_rewritten(lines: list[str]) -> None:
    # Пустые строки и заголовок функции заменены одной строкой: строке 19 нет пары.
    lines[16:19] = ["def binary_search(items, target, steps=0):"]


def long_file(lines: list[str]) -> None:
    two_imports_on_top(lines)
    lines.extend(["# конец"] * 5000)


@pytest.mark.parametrize(
    ("edit", "moved"),
    [
        (line_inside, "Прежние строки теперь — 19–32. "),
        (first_line_rewritten, None),
        (long_file, None),
    ],
)
def test_file_missing_fragment_cut_or_lost(
    edit: Callable[[list[str]], None], moved: str | None
) -> None:
    [finding] = run("file-missing", project=replaced(changed_main(edit)))

    assert "теперь показывает другие строки." in finding.message
    if moved is None:
        assert "Прежние строки" not in finding.message
    else:
        assert moved in finding.message


def fixed_in_place(lines: list[str]) -> None:
    lines[23] = "        middle = low + (high - low) // 2"


def lines_below(lines: list[str]) -> None:
    lines[40:40] = ["", "# Замер на большом массиве"]


@pytest.mark.parametrize("edit", [fixed_in_place, lines_below])
def test_file_missing_fragment_fixed_in_place_or_below(
    edit: Callable[[list[str]], None],
) -> None:
    assert run("file-missing", project=replaced(changed_main(edit))) == []


def test_file_missing_without_history_or_when_listed_after_replace() -> None:
    shifted = changed_main(two_imports_on_top)

    # Истории нет — сдвиг не виден.
    assert run("file-missing", project=replaced(shifted, listed=None)) == []
    # Фрагмент вставили уже по новому файлу: сервис не кладёт его в listed_code.
    assert run("file-missing", project=replaced(shifted, listed=shifted)) == []


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


# Вымышленные замеры: время в секундах из JSON (в том числе с порядком), вывод программы
# в мс, CSV через запятую с десятичной точкой и CSV из Excel по-русски.
MEASUREMENTS = (
    MaterialSource(
        "materials/results.json",
        "ready",
        '{"random": [[500, 0.008508699999993041], [1000, 0.04077499999993961]],\n'
        ' "sorted": [[500, 2.0399999925757584e-05]], "total_s": 2.3349439999999504}\n',
        None,
    ),
    MaterialSource(
        "materials/console.txt", "ready", "n=1000 naive 2.798 мс, сравнений: 124614\n", None
    ),
    MaterialSource("materials/xc.csv", "ready", "f,xc\n100,7234.3\n", None),
    MaterialSource("materials/z.csv", "ready", "f;xc;z\n200;3617,2;3915,8\n", None),
    MaterialSource("materials/runs.csv", "ready", "n,comparisons,swaps\n1000,1302,47550\n", None),
    MaterialSource("materials/model.txt", "ready", "сопротивление 15,734 Ом\n", None),
)


def measured(line: str) -> list[CheckFinding]:
    project = snapshot(progress(f"\\section{{Ход работы}}\n{line}\n"), materials=MEASUREMENTS)
    return run("number-not-in-materials", project=project)


@pytest.mark.parametrize(
    "line",
    [
        # 0,0085087 с: округление и пересчёт в мс.
        "Сортировка 500 элементов заняла 8,51 мс, то есть 0,0085 с.",
        # 2,04e-05 с — в мкс.
        "На упорядоченном входе — 20,4 мкс.",
        # 2,334944 с — в мс до целых; 0,040775 с — в мс до десятых.
        "Всего 2335 мс, из них 40,8 мс на 1000 элементов.",
        # 2,798 мс — до десятых и в секундах.
        "Наивный поиск: 2,8 мс, то есть 0,0028 с.",
        # 7234.3 из CSV через запятую и 3915,8 из CSV через «;».
        "Сопротивления 7234,3 и 3915,8 Ом на частотах 100 и 200 Гц.",
        # Столбцы CSV через запятую без дробей.
        "Сравнений 1302, перестановок 47550, сопротивление 15,73 Ом.",
    ],
)
def test_rounded_and_rescaled_numbers_are_found(line: str) -> None:
    assert measured(line) == []


@pytest.mark.parametrize(
    ("line", "number"),
    [
        ("Сортировка 1000 элементов заняла 12,7 мс.", "12,7"),
        # 8,5087 мс неверно округлено и обрезано.
        ("Сортировка 500 элементов заняла 8,6 мс.", "8,6"),
        ("Сортировка 500 элементов заняла 8,50 мс.", "8,50"),
        # Одна значащая цифра: 0,009 подошло бы к слишком многим числам.
        ("Сортировка 500 элементов заняла 0,009 с.", "0,009"),
        # 124614 сравнений — целое: в другие единицы целые не пересчитываются.
        ("Доля перестановок 0,12.", "0,12"),
        # Из «100,7234.3» не получается 100,7234.
        ("Сопротивление 100,72 Ом.", "100,72"),
        # Дробная часть «15,734» — не отдельное число.
        ("Обработано 734 записи.", "734"),
        # Двузначное целое — счётчик: из 40,775 мс округлением не получается.
        ("Поиск выполнил 41 сравнение.", "41"),
    ],
)
def test_invented_numbers_are_still_caught(line: str, number: str) -> None:
    [finding] = measured(line)

    assert finding.message.startswith(f"Чисел {number} нет в ваших материалах.")


def test_number_check_is_incomplete_while_materials_are_read() -> None:
    materials = (*MATERIALS, MaterialSource("materials/out2.txt", "pending", None, None))
    project = snapshot(progress(NUMBERS), materials=materials)

    found = run("number-not-in-materials", project=project)

    assert all(
        finding.message.endswith(" Сверка неполная: не прочитаны materials/out2.txt.")
        for finding in found
    )
    assert places(found) == [(PROGRESS, 8), (PROGRESS, 11)]
