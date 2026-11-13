"""Проверки рисунков, таблиц, листингов и ссылок на примерах из docs/checks.md."""

import pytest

from tests.checks_samples import lab_files, places, run

PROGRESS = "sections/progress.tex"


def progress(text: str) -> dict[str, str]:
    return {PROGRESS: text}


CAPTION_MISSING = r"""\section{Ход работы}
Окно программы показано на рисунке~\ref{fig:run}.
\bbtScreenshot{materials/run.png}{}{fig:run}
Результаты замеров:
\begin{tabular}{|r|c|}
  \hline
  Длина массива & Время, с \\ \hline
  1000 & 0,0042 \\ \hline
\end{tabular}
"""


def test_caption_missing_example() -> None:
    found = run("caption-missing", progress(CAPTION_MISSING))

    assert places(found) == [(PROGRESS, 3), (PROGRESS, 5)]
    assert [finding.message for finding in found] == [
        "У рисунка нет подписи: в PDF после номера пусто — «Рисунок N – ». Напишите, что на "
        "нём, с прописной буквы — или попросите ИИ.",
        "Таблица вставлена без подписи и номера. Попросите ИИ добавить подпись.",
    ]
    assert {finding.level for finding in found} == {"error"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "\\begin{bbttable}{ }{tab:t}\n\\begin{tabular}{|r|}\n1 \\\\\n\\end{tabular}\n"
            "\\end{bbttable}",
            "У таблицы нет подписи: в PDF после номера пусто — «Таблица N – ». Напишите, что на "
            "нём, с прописной буквы — или попросите ИИ.",
        ),
        (
            "\\begin{bbtcode}{python}{}{lst:a}\nprint(1)\n\\end{bbtcode}",
            "У листинга нет подписи: в PDF после номера пусто — «Листинг N – ». Напишите, что "
            "на нём, с прописной буквы — или попросите ИИ.",
        ),
        (
            "\\begin{figure}\n\\includegraphics{materials/run.png}\n\\label{fig:a}\n\\end{figure}",
            "У рисунка нет подписи: в PDF после номера пусто — «Рисунок N – ». Напишите, что на "
            "нём, с прописной буквы — или попросите ИИ.",
        ),
        (
            "\\begin{lstlisting}[language=Python]\nprint(1)\n\\end{lstlisting}",
            "У листинга нет подписи: в PDF после номера пусто — «Листинг N – ». Напишите, что "
            "на нём, с прописной буквы — или попросите ИИ.",
        ),
        (
            "\\includegraphics[width=5cm]{materials/run.png}",
            "Картинка materials/run.png вставлена без подписи и номера. Попросите ИИ оформить "
            "её как рисунок с подписью.",
        ),
        (
            "\\begin{verbatim}\nprint(1)\n\\end{verbatim}",
            "Код вставлен без подписи и номера. Попросите ИИ оформить его как листинг с подписью.",
        ),
    ],
)
def test_caption_missing_kinds(text: str, message: str) -> None:
    found = run("caption-missing", progress(f"\\section{{Ход работы}}\n{text}\n"))

    assert [(finding.line, finding.message) for finding in found] == [(2, message)]


@pytest.mark.parametrize(
    "text",
    [
        "\\bbtScreenshot{materials/run.png}{Окно программы}{}",
        "\\begin{bbttable}{Время поиска}{tab:time}\n\\begin{tabular}{|r|}\n1 \\\\\n"
        "\\end{tabular}\n\\end{bbttable}",
        "\\begin{figure}\n\\includegraphics{materials/run.png}\n\\caption{Окно программы}\n"
        "\\end{figure}",
        "\\begin{lstlisting}[caption={Код, часть 1}, label=lst:a]\nprint(1)\n\\end{lstlisting}",
        "\\lstinputlisting[caption=Программа]{materials/main.py}",
    ],
)
def test_caption_missing_does_not_fire(text: str) -> None:
    assert run("caption-missing", progress(f"\\section{{Ход работы}}\n{text}\n")) == []


CAPTION_FORMAT = r"""\section{Ход работы}
Окно программы показано на рисунке~\ref{fig:run}, время поиска — в таблице~\ref{tab:time}.
\bbtScreenshot{materials/run.png}{окно программы после запуска.}{fig:run}
\begin{bbttable}{Таблица 1 -- Время поиска}{tab:time}
  \begin{tabular}{|r|c|}
    \hline
    Длина массива & Время, с \\ \hline
    1000 & 0,0042 \\ \hline
  \end{tabular}
\end{bbttable}
"""


def test_caption_format_example() -> None:
    found = run("caption-format", progress(CAPTION_FORMAT))

    assert places(found) == [(PROGRESS, 3), (PROGRESS, 4)]
    assert [finding.message for finding in found] == [
        "Подпись «окно программы после запуска.»: начните с прописной буквы, уберите точку "
        "в конце.",
        "Подпись «Таблица 1 -- Время поиска»: уберите «Таблица 1 --» — номер ставится сам.",
    ]
    assert {finding.level for finding in found} == {"warning"}


@pytest.mark.parametrize(
    "caption",
    [
        "Окно программы после запуска",
        "Функция main()",
        "pandas после загрузки",
        "Вывод программы, часть 2",
        "Окно программы...",
        "Рисунки и схемы",
    ],
)
def test_caption_format_does_not_fire(caption: str) -> None:
    text = f"\\section{{Ход работы}}\n\\bbtScreenshot{{materials/run.png}}{{{caption}}}{{fig:a}}\n"

    assert run("caption-format", progress(text)) == []


REF_BROKEN = r"""\section{Ход работы}
Окно программы показано на рисунке~\ref{fig:result}, повторный запуск — на рисунке~\ref{fig:run}.
\bbtScreenshot{materials/run.png}{Окно программы}{fig:run}
\bbtScreenshot{materials/run.png}{Повторный запуск}{fig:run}
Алгоритм описан в методичке~\cite{metod}.
"""


def test_ref_broken_example() -> None:
    found = run("ref-broken", progress(REF_BROKEN))

    assert places(found) == [(PROGRESS, 2), (PROGRESS, 4), (PROGRESS, 5)]
    assert [finding.message for finding in found] == [
        "В PDF здесь «??» вместо номера: ссылка ведёт на рисунок, таблицу или листинг, "
        "которого нет. Попросите ИИ исправить ссылку.",
        "Одна метка «fig:run» у двух элементов (строки 3 и 4): ссылки на второй покажут номер "
        "первого. Попросите ИИ исправить метку.",
        "В PDF здесь «[?]»: источника «metod» нет в списке источников. Попросите ИИ добавить "
        "источник из материалов или убрать ссылку.",
    ]


def test_ref_broken_does_not_fire() -> None:
    text = (
        "\\section{Ход работы}\n% Ссылка~\\ref{fig:nothing} в комментарии.\n"
        "Код — в приложении~\\ref{app:code}, время — по формуле~\\eqref{eq:time}.\n"
        "\\begin{equation}\\label{eq:time}\nT = c\n\\end{equation}\n"
    )
    main = lab_files()["main.tex"].replace(
        "\\end{document}",
        "\\appendix\n\\section{Программа поиска}\\label{app:code}\n"
        "\\bbtCodeFile[python]{materials/main.py}{Программа поиска}{lst:main}\n\\end{document}",
    )

    assert run("ref-broken", {PROGRESS: text, "main.tex": main}) == []


def test_ref_broken_repeated_bibitem() -> None:
    main = lab_files()["main.tex"].replace(
        "\\end{document}",
        "\\begin{thebibliography}{9}\n\\bibitem{metod} Методичка.\n\\bibitem{metod} Ещё раз.\n"
        "\\end{thebibliography}\n\\end{document}",
    )

    found = run("ref-broken", {"main.tex": main})

    assert [(finding.file, "metod" in finding.message) for finding in found] == [("main.tex", True)]


REF_MISSING = r"""\section{Ход работы}
Программа запущена, окно показано ниже.
\bbtScreenshot{materials/run.png}{Окно программы}{fig:run}
Время поиска оценивается по формуле
\begin{equation}\label{eq:time}
  T(n) = c \cdot \log_2 n.
\end{equation}
"""


def test_ref_missing_example() -> None:
    found = run("ref-missing", progress(REF_MISSING))

    assert places(found) == [(PROGRESS, 3), (PROGRESS, 5)]
    assert [finding.message for finding in found] == [
        "На рисунок «Окно программы» нет ссылки в тексте. По правилам на каждый ссылаются: «на "
        "рисунке 3.1», «в таблице 3.1». Попросите ИИ добавить ссылку.",
        "У формулы есть номер, но ссылки на неё нет. Формулы без ссылок пишут без номера. "
        "Попросите ИИ убрать номер или сослаться на формулу.",
    ]


def test_ref_missing_does_not_fire() -> None:
    goal = "\\section{Цель работы}\nОкно — на рисунке~\\ref{fig:run}.\n"
    text = (
        "\\section{Ход работы}\n\\bbtScreenshot{materials/run.png}{Окно программы}{fig:run}\n"
        "\\bbtScreenshot{materials/run.png}{Как на рисунке~\\ref{fig:two}}{fig:one}\n"
        "\\bbtScreenshot{materials/run.png}{Второе окно, см. рисунок~\\ref{fig:one}}{fig:two}\n"
        "\\[ T = c \\]\n\\begin{equation*}\nT = c\n\\end{equation*}\n"
        "\\begin{equation}\nT = c \\nonumber\n\\end{equation}\n"
        "\\begin{align}\na &= b \\nonumber \\\\\nc &= d \\notag\n\\end{align}\n"
    )

    assert run("ref-missing", {"sections/goal.tex": goal, PROGRESS: text}) == []


def test_ref_in_own_caption_does_not_count() -> None:
    text = (
        "\\section{Ход работы}\n"
        "\\bbtScreenshot{materials/run.png}{Окно (рисунок~\\ref{fig:run})}{fig:run}\n"
    )

    assert places(run("ref-missing", progress(text))) == [(PROGRESS, 2)]


def test_ref_missing_appendix_and_source() -> None:
    main = lab_files()["main.tex"].replace(
        "\\end{document}",
        "\\begin{thebibliography}{9}\n\\bibitem{python} Документация Python.\n"
        "\\end{thebibliography}\n\\appendix\n\\section{Программа поиска}\\label{app:code}\n"
        "Текст приложения.\n\\end{document}",
    )

    found = run("ref-missing", {"main.tex": main})

    assert [finding.message for finding in found] == [
        "На источник «Документация Python.» нет ссылки в тексте. Попросите ИИ добавить "
        "ссылку или убрать источник.",
        "На приложение «Программа поиска» нет ссылки в тексте, например «(приложение А)». "
        "Попросите ИИ добавить ссылку.",
    ]


def test_ref_missing_align_rows() -> None:
    text = (
        "\\section{Ход работы}\nСм.~\\eqref{eq:a}.\n\\begin{align}\n"
        "a &= b \\label{eq:a} \\\\\n  c &= d\n\\end{align}\n"
    )

    assert places(run("ref-missing", progress(text))) == [(PROGRESS, 5)]


def test_ref_after_example() -> None:
    text = (
        "\\section{Ход работы}\n\\bbtScreenshot{materials/run.png}{Окно программы}{fig:run}\n"
        "Окно программы показано на рисунке~\\ref{fig:run}.\n"
    )

    [finding] = run("ref-after", progress(text))

    assert (finding.file, finding.line, finding.level) == (PROGRESS, 2, "warning")
    assert finding.message == (
        "Ссылка на рисунок «Окно программы» стоит после него. По правилам сначала пишут «Окно "
        "показано на рисунке 3.1», потом ставят сам рисунок. Попросите ИИ переставить."
    )


def test_ref_after_does_not_fire() -> None:
    goal = "\\section{Цель работы}\nОкно — на рисунке~\\ref{fig:run}.\n"
    text = (
        "\\section{Ход работы}\n\\bbtScreenshot{materials/run.png}{Окно программы}{fig:run}\n"
        "Снова рисунок~\\ref{fig:run}.\n"
        "Таблица~\\ref{tab:t}: \\begin{bbttable}{Время}{tab:t}\n\\begin{tabular}{|r|}\n"
        "1 \\\\\n\\end{tabular}\n\\end{bbttable}\nКод — в листинге~\\ref{lst:main}.\n"
    )
    main = lab_files()["main.tex"].replace(
        "\\end{document}",
        "\\appendix\n\\section{Программа поиска}\\label{app:code}\n"
        "\\bbtCodeFile[python]{materials/main.py}{Программа поиска}{lst:main}\n\\end{document}",
    )

    assert run("ref-after", {"sections/goal.tex": goal, PROGRESS: text, "main.tex": main}) == []


def test_listing_too_long_example() -> None:
    text = (
        "\\section{Ход работы}\nПрограмма приведена в листинге~\\ref{lst:main}.\n"
        "\\bbtCodeFile[python]{materials/main.py}{Программа поиска}{lst:main}\n"
    )

    [finding] = run("listing-too-long", progress(text))

    assert (finding.file, finding.line, finding.level) == (PROGRESS, 3, "warning")
    assert finding.message == (
        "Листинг «Программа поиска» — 85 строк. В тексте оставляют до 40 строк главного кода, "
        "а весь код переносят в приложение и ссылаются на него. Попросите ИИ перенести код "
        "в приложение."
    )


def code_section(code: str) -> str:
    """Ход работы с одним листингом bbtcode."""
    return (
        f"\\section{{Ход работы}}\n\\begin{{bbtcode}}{{python}}{{Код}}{{lst:a}}\n{code}\n"
        "\\end{bbtcode}\n"
    )


def test_listing_too_long_does_not_fire() -> None:
    forty = "\n".join(f"print({number})" for number in range(40))
    text = code_section(forty)
    main = lab_files()["main.tex"].replace(
        "\\end{document}",
        "\\appendix\n\\section{Программа поиска}\\label{app:code}\n"
        "\\bbtCodeFile[python]{materials/main.py}{Программа поиска}{lst:main}\n\\end{document}",
    )

    assert run("listing-too-long", {PROGRESS: text, "main.tex": main}) == []


def test_listing_too_long_counts_code_environment_lines() -> None:
    lines = "\n".join(["print(1)", "", *[f"x = {n}" for n in range(39)]])
    text = code_section(lines)

    [finding] = run("listing-too-long", progress(text))

    assert "— 41 строк" in finding.message
