"""Примеры проверок по PDF из docs/checks.md: проект для примеров с этими файлами собран
компилятором из docker compose, логи лежат в tests/fixtures/checks/*.log.

Те же примеры собирает тест с настоящим компилятором (uv run pytest -m compiler):
так видно, что логи фикстур не устарели.
"""

PROGRESS = "sections/progress.tex"
CONCLUSION = "sections/conclusion.tex"

# text-overflow: длинное имя функции и таблица шире страницы. Имя — без «_», «.», «(»:
# после них моноширинный текст переносится.
_OVERFLOW_LINES = [
    r"\section{Ход работы}",
    r"\subsection{Бинарный поиск}",
    r"Для замера времени написана функция "
    r"\texttt{measureAverageExecutionTimeOfBinarySearchInSortedArraysAndLists}.",
    r"Время поиска приведено в таблице~\ref{tab:time}.",
    r"\begin{bbttable}{Время поиска, с}{tab:time}",
    r"  \begin{tabular}{|r|c|c|c|c|}",
    r"    \hline",
    r"    Длина массива & Линейный поиск в неотсортированном массиве & Бинарный поиск "
    r"в отсортированном массиве & Интерполяционный поиск & Поиск по хеш-таблице \\ \hline",
    r"    1000 & 0,0042 & 0,0038 & 0,0031 & 0,0001 \\ \hline",
    r"  \end{tabular}",
    r"\end{bbttable}",
]
OVERFLOW = {PROGRESS: "\n".join(_OVERFLOW_LINES) + "\n"}
# text-overflow в последнем абзаце раздела: абзац кончается на \section следующего файла,
# и лог пишет «in paragraph at lines 2--1», когда открыт уже sections/conclusion.tex.
OVERFLOW_AT_END = {
    PROGRESS: "\n".join(
        [
            r"\section{Ход работы}",
            r"Для замера времени написана функция "
            r"\texttt{measureAverageExecutionTimeOfBinarySearchInSortedArraysAndLists}.",
        ]
    )
    + "\n"
}
# text-overflow в формулах: equation и \[…\] шире поля. Лог пишет «detected at line N» —
# строку, где формула кончилась (\end{equation}, \]).
_SUM = " + ".join(f"t_{{{index}}}" for index in range(1, 30))
FORMULA = {
    PROGRESS: "\n".join(
        [
            r"\section{Ход работы}",
            r"Время сортировки складывается из времени всех проходов:",
            r"\begin{equation}",
            rf"  T(n) = {_SUM},",
            r"\end{equation}",
            r"где $t_i$ — время $i$-го прохода. Для проверки посчитана сумма",
            r"\[",
            rf"  S = {_SUM}.",
            r"\]",
            r"Короткая формула $T = t_1 + t_2$ помещается в строку.",
        ]
    )
    + "\n"
}
# missing-glyph: эмодзи в выводе программы.
GLYPH = {
    CONCLUSION: r"""\section{Выводы}
Программа выводит строку из листинга~\ref{lst:out}.
\begin{bbtcode}{text}{Вывод программы}{lst:out}
✅ Бинарный поиск: индекс 7, 0.0038 с
\end{bbtcode}
""",
}
# build-failed: перечисление не закрыто.
UNCLOSED = {
    CONCLUSION: r"""\section{Выводы}
\begin{itemize}
  \item реализованы линейный и бинарный поиск.
""",
}
SAMPLES = {"overflow": OVERFLOW, "formula": FORMULA, "glyph": GLYPH, "unclosed": UNCLOSED}
