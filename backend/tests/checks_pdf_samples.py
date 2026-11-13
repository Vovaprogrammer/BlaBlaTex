"""Примеры проверок по PDF из docs/checks.md: проект для примеров с этими файлами собран
компилятором из docker compose, логи лежат в tests/fixtures/checks/*.log.

Те же примеры собирает тест с настоящим компилятором (uv run pytest -m compiler):
так видно, что логи фикстур не устарели.
"""

PROGRESS = "sections/progress.tex"
CONCLUSION = "sections/conclusion.tex"

# text-overflow: длинное имя функции и таблица шире страницы.
_OVERFLOW_LINES = [
    r"\section{Ход работы}",
    r"\subsection{Бинарный поиск}",
    r"Для замера времени написана функция "
    r"\texttt{measure\_average\_execution\_time\_of\_binary\_search\_in\_sorted\_arrays}.",
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
SAMPLES = {"overflow": OVERFLOW, "glyph": GLYPH, "unclosed": UNCLOSED}
