import React from 'react';
import { FileText, X, Beaker, BookOpen, GraduationCap, Presentation, PenTool } from 'lucide-react';

interface TemplatesPanelProps {
    onInsertCode: (code: string) => void;
    onClose: () => void;
}

const LAB_WORK_TEMPLATE = `\\documentclass[14pt,a4paper]{extarticle}
\\usepackage[utf8]{inputenc}
\\usepackage[T2A]{fontenc}
\\usepackage[russian]{babel}
\\usepackage{amsmath, amssymb, amsfonts}
\\usepackage{graphicx}
\\usepackage{float}
\\usepackage{geometry}
\\geometry{top=2cm, bottom=2cm, left=2cm, right=2cm}
\\usepackage{enumitem}
\\usepackage{hyperref}
\\usepackage{caption}
\\usepackage{subcaption}
\\usepackage{xcolor}
\\usepackage{tempora}
\\usepackage{setspace}
\\onehalfspacing
\\usepackage{minted}

\\renewcommand{\\rmdefault}{tempora}
\\renewcommand{\\sfdefault}{tempora}
\\renewcommand{\\ttdefault}{tempora}

\\usemintedstyle{vs}

\\usepackage{etoolbox}
\\BeforeBeginEnvironment{minted}{\\vspace{0.5cm}}
\\AfterEndEnvironment{minted}{\\vspace{0.5cm}}

\\setminted{
    frame=single,
    framesep=8mm,
    baselinestretch=1.2,
    fontsize=\\small,
    breaklines=true,
    tabsize=4,
    linenos=false
}

\\usepackage[hyphens]{url}
\\usepackage{microtype}

\\begin{document}

% ========== НАЧАЛО ОТЧЁТА ==========

\\section*{Цель работы}
\\textit{Текст цели работы...}

\\section*{Задания}
\\textit{Описание заданий...}

\\begin{enumerate}
    \\item \\textbf{Задание 1:} Описание задания...
    \\item \\textbf{Задание 2:} Описание задания...
    \\item \\textbf{Задание 3:} Описание задания...
\\end{enumerate}

\\section*{Ход выполнения работы}

\\subsection*{Задание 1. Название задания}
Описание выполняемых действий...

\\begin{minted}[frame=single, fontsize=\\small, breaklines, tabsize=4]{python}
# Ваш код
\\end{minted}

\\begin{figure}[H]
    \\centering
    \\includegraphics[width=0.7\\textwidth]{example-image}
    \\caption{Результат выполнения задания 1 (скриншот)}
    \\label{fig:task1}
\\end{figure}

\\subsection*{Задание 2. Название задания}
Описание выполняемых действий...

\\begin{minted}[frame=single, fontsize=\\small, breaklines, tabsize=4]{python}
# Ваш код
\\end{minted}

\\begin{figure}[H]
    \\centering
    \\includegraphics[width=0.7\\textwidth]{example-image}
    \\caption{Результат выполнения задания 2 (скриншот)}
    \\label{fig:task2}
\\end{figure}

\\subsection*{Задание 3. Название задания}
Описание выполняемых действий...

\\begin{minted}[frame=single, fontsize=\\small, breaklines, tabsize=4]{python}
# Ваш код
\\end{minted}

\\begin{figure}[H]
    \\centering
    \\includegraphics[width=0.7\\textwidth]{example-image}
    \\caption{Результат выполнения задания 3 (скриншот)}
    \\label{fig:task3}
\\end{figure}

\\newpage

\\section*{Результаты}
\\begin{table}[H]
\\centering
\\begin{tabular}{|c|c|c|}
\\hline
\\textbf{ } & \\textbf{ } & \\textbf{ } \\\\
\\hline
Пример 1 & значение & значение \\\\
Пример 2 & значение & значение \\\\
\\hline
\\end{tabular}
\\caption{Сравнение результатов}
\\label{tab:results}
\\end{table}

\\section*{Вывод}

\\end{document}`;

const SCIENTIFIC_ARTICLE_TEMPLATE = `\\documentclass[10pt,a4paper,twocolumn]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T2A]{fontenc}
\\usepackage[russian]{babel}
\\usepackage{amsmath, amssymb, amsfonts}
\\usepackage{mathtools}
\\usepackage{polynom}
\\usepackage{array}
\\usepackage{xcolor}
\\usepackage{geometry}
\\geometry{left=20mm, right=20mm, top=20mm, bottom=20mm}

% === ЗАГОЛОВКИ ЖИРНЫМ ===
\\usepackage{titlesec}
\\titleformat{\\section}
  {\\normalsize\\bfseries\\centering}
  {\\thesection}{1em}{}
\\titleformat{\\subsection}
  {\\normalsize\\bfseries}
  {\\thesubsection}{1em}{}
\\titleformat{\\subsubsection}
  {\\normalsize\\bfseries}
  {\\thesubsubsection}{1em}{}

% === ОТСТУПЫ В ТАБЛИЦАХ И РИСУНКАХ ===
\\usepackage{color}
\\AtBeginEnvironment{tabular}{\\setlength{\\parindent}{0pt}}
\\AtBeginEnvironment{figure}{\\setlength{\\parindent}{0pt}}

% === НАСТРОЙКА КОЛОНТИТУЛОВ (опционально) ===
\\usepackage{fancyhdr}
\\pagestyle{fancy}
\\fancyhf{}
\\fancyfoot[C]{\\thepage}
\\renewcommand{\\headrulewidth}{0pt}

\\begin{document}

% ========== ШАПКА (одна колонка) ==========
\\twocolumn[
  \\begin{@twocolumnfalse}
    \\begin{center}
      \\textbf{\\large НАЗВАНИЕ СЕКЦИИ / КОНФЕРЕНЦИИ}
    \\end{center}

    \\begin{center}
      \\textbf{\\Large НАЗВАНИЕ ДОКЛАДА (ЗАГЛАВНЫМИ БУКВАМИ)}
    \\end{center}

    \\begin{it}
      \\begin{center}
        \\textbf{Автор 1 (Фамилия И.О.)},\\\\
        ученая степень, звание, должность, место работы, город, страна, \\\\
        email@example.com \\\\
        \\textbf{Автор 2 (Фамилия И.О.)},\\\\
        группа / статус, место работы, город, страна, \\\\
        email@example.com
      \\end{center}
    \\end{it}

    \\textit{Ключевые слова: слово 1, слово 2, слово 3, слово 4, слово 5.}

    \\vspace{0.5cm}
  \\end{@twocolumnfalse}
]

% ========== АННОТАЦИЯ ==========
\\begin{center}
\\textbf{Аннотация}
\\end{center}
Здесь кратко описывается суть работы: что рассматривается, какие методы используются, какие результаты получены. Объём аннотации — 50–150 слов. Аннотация пишется в настоящем времени.

\\section*{Введение}
Введение содержит обоснование актуальности темы, краткий обзор литературы, постановку проблемы. Формулируются цель и задачи работы.

\\section*{Основные определения и теоремы}
В этом разделе вводятся необходимые определения и формулируются ключевые теоремы, на которые опирается работа. Для каждой теоремы желательно привести доказательство или ссылку на него.

\\subsection*{Определение 1}
Текст определения.

\\subsection*{Теорема 1 (Название)}
Формулировка теоремы.

\\subsection*{Доказательство}
Текст доказательства.

\\section*{Метод / Алгоритм}
Описывается предлагаемый метод или алгоритм. Приводятся формулы, пояснения, блок-схемы.

Пример формулы с пояснением переменных:

\\begin{equation}
\\label{eq:main}
V = \\frac{S}{t},
\\end{equation}

где $V$ — скорость, м/с; $S$ — пройденное расстояние, м; $t$ — время, с.

\\subsection*{Пример}
Иллюстрация работы метода на конкретном примере.

\\section*{Результаты}
Представляются полученные результаты. Возможно представление в виде таблиц, графиков, диаграмм.

\\begin{center}
\\begin{tabular}{|c|c|}
\\hline
\\textbf{Параметр} & \\textbf{Значение} \\\\
\\hline
A & 10 \\\\
B & 20 \\\\
\\hline
\\end{tabular}
\\end{center}

\\section*{Обсуждение}
Анализируются полученные результаты. Сравнение с известными аналогами. Объяснение неожиданных эффектов. Ограничения применимости метода.

\\section*{Заключение}
Формулируются основные выводы работы:
\\begin{itemize}
    \\item вывод 1;
    \\item вывод 2;
    \\item вывод 3.
\\end{itemize}
Указываются направления для дальнейших исследований.

\\section*{Благодарности}
Выражается благодарность научному руководителю, коллегам, организациям за финансовую поддержку (указываются гранты).

\\begin{thebibliography}{99}
\\bibitem{ref1} Автор И.И. Название книги. — М.: Издательство, 2024. — 300 с.
\\bibitem{ref2} Автор П.П. Название статьи // Название журнала. — 2025. — Т. 10, № 2. — С. 45–52.
\\bibitem{ref3} Автор А.А. Название работы [Электронный ресурс]. — URL: http://example.com (дата обращения: 29.04.2026).
\\end{thebibliography}

\\end{document}`;

const VAK_ARTICLE_TEMPLATE = `\\documentclass[14pt,a4paper]{extarticle}
\\usepackage[utf8]{inputenc}
\\usepackage[T2A]{fontenc}
\\usepackage[russian]{babel}
\\usepackage{amsmath, amssymb, amsfonts}
\\usepackage{graphicx}
\\usepackage{float}
\\usepackage{geometry}
\\geometry{top=2cm, bottom=2cm, left=3cm, right=1.5cm}
\\usepackage{setspace}
\\onehalfspacing
\\usepackage{tempora}
\\renewcommand{\\rmdefault}{tempora}
\\usepackage{hyperref}
\\usepackage{caption}
\\usepackage{subcaption}
\\usepackage{enumitem}
\\usepackage{indentfirst}
\\setlength{\\parindent}{1.25cm}
\\usepackage{etoolbox}
\\AtBeginEnvironment{tabular}{\\small}
\\usepackage{array}
\\usepackage{longtable}
\\usepackage{multirow}

% Настройка гиперссылок
\\hypersetup{
    colorlinks=true,
    linkcolor=black,
    citecolor=black,
    urlcolor=blue
}

% Настройка подписей к рисункам и таблицам
\\captionsetup{labelsep=period, justification=centering}
\\renewcommand{\\thetable}{\\arabic{table}}
\\renewcommand{\\thefigure}{\\arabic{figure}}

% Нумерация страниц
\\usepackage{fancyhdr}
\\pagestyle{fancy}
\\fancyhf{}
\\fancyfoot[C]{\\thepage}
\\renewcommand{\\headrulewidth}{0pt}

% Для DOI
\\usepackage{doi}
\\renewcommand{\\doi}[1]{\\href{https://doi.org/#1}{#1}}

\\begin{document}

% ==================== РУССКАЯ ЧАСТЬ ====================

% УДК (обязательный элемент)
\\noindent УДК \\underline{\\hspace{4cm}}
\\vspace{1cm}

% НАЗВАНИЕ СТАТЬИ (рус)
\\begin{center}
    {\\Large \\textbf{Название статьи должно точно отражать предмет и объект исследования}} \\\\
    \\vspace{0.5cm}
    {\\large \\textbf{Краткое и лаконичное название}}
\\end{center}
\\vspace{0.5cm}

% СВЕДЕНИЯ ОБ АВТОРАХ (рус)
\\noindent
\\textbf{И.И. Иванов}, доктор физико-математических наук, профессор \\\\
ФГБОУ ВО «Московский государственный университет им. М.В. Ломоносова», г. Москва, Россия \\\\
\\textit{E-mail: ivanov@msu.ru} \\\\
\\textit{ORCID: 0000-0000-0000-0000}
\\vspace{0.3cm}

\\noindent
\\textbf{П.П. Петров}, кандидат технических наук, доцент \\\\
ФГБОУ ВО «Санкт-Петербургский политехнический университет», г. Санкт-Петербург, Россия \\\\
\\textit{E-mail: petrov@spbstu.ru} \\\\
\\textit{ORCID: 0000-0000-0000-0000}
\\vspace{0.3cm}

\\noindent
\\textbf{А.А. Сидоров}, аспирант \\\\
ФГБОУ ВО «Новосибирский национальный исследовательский государственный университет», г. Новосибирск, Россия \\\\
\\textit{E-mail: sidorov@nsu.ru} \\\\
\\vspace{1cm}

% АННОТАЦИЯ (рус)
\\noindent\\textbf{Аннотация.} \\textit{Здесь кратко описывается суть работы: проблема, метод, результат. Объём — от 100 до 250 слов. Аннотация пишется в настоящем времени, без оценок и ссылок на литературу.}
\\vspace{0.5cm}

% КЛЮЧЕВЫЕ СЛОВА (рус)
\\noindent\\textbf{Ключевые слова:} \\textit{ключевое слово 1, ключевое слово 2, ключевое слово 3, ключевое слово 4, ключевое слово 5, ключевое слово 6, ключевое слово 7, ключевое слово 8, ключевое слово 9, ключевое слово 10.}
\\vspace{1cm}

% ==================== АНГЛИЙСКАЯ ЧАСТЬ ====================

% НАЗВАНИЕ СТАТЬИ (англ)
\\begin{center}
    {\\Large \\textbf{Title of the Article}} \\\\
    \\vspace{0.5cm}
    {\\large \\textbf{Short and Concise Title}}
\\end{center}
\\vspace{0.5cm}

% СВЕДЕНИЯ ОБ АВТОРАХ (англ)
\\noindent
\\textbf{I.I. Ivanov}, Doctor of Physical and Mathematical Sciences, Professor \\\\
Lomonosov Moscow State University, Moscow, Russia \\\\
\\textit{E-mail: ivanov@msu.ru} \\\\
\\textit{ORCID: 0000-0000-0000-0000}
\\vspace{0.3cm}

\\noindent
\\textbf{P.P. Petrov}, Candidate of Technical Sciences, Associate Professor \\\\
Peter the Great St. Petersburg Polytechnic University, St. Petersburg, Russia \\\\
\\textit{E-mail: petrov@spbstu.ru} \\\\
\\textit{ORCID: 0000-0000-0000-0000}
\\vspace{0.3cm}

\\noindent
\\textbf{A.A. Sidorov}, Postgraduate Student \\\\
Novosibirsk State University, Novosibirsk, Russia \\\\
\\textit{E-mail: sidorov@nsu.ru} \\\\
\\vspace{1cm}

% АННОТАЦИЯ (англ)
\\noindent\\textbf{Abstract.} \\textit{English translation of the annotation. The article considers the problem... The authors propose a method... The experimental study found... The obtained data indicate... The work has practical significance for...}
\\vspace{0.5cm}

% КЛЮЧЕВЫЕ СЛОВА (англ)
\\noindent\\textbf{Keywords:} \\textit{keyword 1, keyword 2, keyword 3, keyword 4, keyword 5, keyword 6, keyword 7, keyword 8, keyword 9, keyword 10.}
\\vspace{1cm}

% DOI (обязательный для ВАК/РИНЦ)
\\noindent\\textit{DOI: \\href{https://doi.org/10.0000/example}{10.0000/example}} (будет присвоен издательством)

\\newpage

% ==================== ОСНОВНОЙ ТЕКСТ ====================

\\section*{Введение}
\\addcontentsline{toc}{section}{Введение}

Здесь описывается актуальность исследования. Обосновывается необходимость проведения работы. Проводится краткий обзор литературы по теме. Формулируется проблема, цель и задачи исследования.

\\textit{Примерный план введения:}
\\begin{itemize}
    \\item Актуальность темы (почему это важно сейчас)
    \\item Степень разработанности проблемы (кто и что уже сделал)
    \\item Цель исследования (чего хотим достичь)
    \\item Задачи исследования (шаги для достижения цели)
    \\item Научная новизна (что делаем впервые)
    \\item Практическая значимость (где можно применить)
\\end{itemize}

\\section*{Методология и методы исследования}
\\addcontentsline{toc}{section}{Методология и методы исследования}

Описываются используемые методы, оборудование, программное обеспечение. Указываются объекты исследования, объём выборки, критерии отбора. Детали должны быть достаточными для воспроизведения эксперимента другим исследователем.

\\subsection*{Объект исследования}
Описание объекта.

\\subsection*{Методы сбора и обработки данных}
Описание методов.

\\subsection*{Статистическая обработка}
Какие статистические критерии использовались.

\\section*{Результаты исследования}
\\addcontentsline{toc}{section}{Результаты исследования}

Представляются только фактические данные. Без интерпретации. Результаты могут быть в виде текста, таблиц, графиков, диаграмм.

\\subsection*{Пример оформления таблицы}

Перед таблицей в тексте обязательно даётся ссылка: «Результаты измерений представлены в табл. 1».

\\begin{table}[H]
\\centering
\\caption{Краткое название таблицы}
\\begin{tabular}{|c|c|c|}
\\hline
\\textbf{Параметр} & \\textbf{Контрольная группа} & \\textbf{Экспериментальная группа} \\\\
\\hline
Показатель 1 & 12.5 $\\pm$ 0.3 & 15.8 $\\pm$ 0.4 \\\\
Показатель 2 & 8.2 $\\pm$ 0.2 & 10.1 $\\pm$ 0.3 \\\\
Показатель 3 & 45.6 $\\pm$ 1.2 & 42.3 $\\pm$ 1.1 \\\\
\\hline
\\end{tabular}
\\end{table}

\\subsection*{Пример оформления рисунка}

Перед рисунком в тексте обязательно даётся ссылка: «На рис. 1 представлена зависимость...»

\\begin{figure}[H]
\\centering
\\includegraphics[width=0.7\\textwidth]{example-image}
\\caption{Краткое название рисунка}
\\label{fig:result}
\\end{figure}

\\subsection*{Пример оформления формулы}

Расчёт производился по формуле (1):

\\begin{equation}
\\label{eq:velocity}
V = \\frac{S}{t},
\\end{equation}

где $V$ — скорость, м/с;

$S$ — пройденное расстояние, м;

$t$ — время, с.

\\section*{Обсуждение результатов}
\\addcontentsline{toc}{section}{Обсуждение результатов}

Здесь даётся интерпретация полученных результатов. Сравнение с данными других авторов. Объяснение неожиданных результатов. Ограничения исследования.

\\section*{Заключение}
\\addcontentsline{toc}{section}{Заключение}

Формулируются основные выводы исследования. Указывается, достигнута ли цель, решены ли поставленные задачи. Даются рекомендации и направления для будущих исследований.

\\section*{Благодарности}
\\addcontentsline{toc}{section}{Благодарности}

Выражается благодарность научному руководителю, коллегам, рецензентам. Указываются источники финансирования (гранты).

\\section*{Конфликт интересов}
\\addcontentsline{toc}{section}{Конфликт интересов}

Авторы заявляют об отсутствии конфликта интересов.

% ==================== СПИСОК ЛИТЕРАТУРЫ ====================

\\begin{thebibliography}{99}
\\addcontentsline{toc}{section}{Список литературы}

\\bibitem{ref1} Иванов И.И. Название книги. — М.: Издательство, 2023. — 300 с.

\\bibitem{ref2} Петров П.П. Название статьи // Название журнала. — 2024. — Т. 10, № 2. — С. 45–52.

\\bibitem{ref3} Сидоров А.А. Название диссертации: дис. ... канд. техн. наук. — Новосибирск, 2023. — 180 с.

\\bibitem{ref4} Smith J. Article title // Journal Name. — 2023. — Vol. 15, No. 3. — P. 112–120. — DOI: 10.0000/example.

\\bibitem{ref5} Название электронного ресурса [Электронный ресурс]. — URL: http://example.com (дата обращения: 15.04.2026).

\\end{thebibliography}

\\end{document}`;

const PRESENTATION_TEMPLATE = `\\documentclass[14pt,aspectratio=169]{beamer}
\\usepackage[utf8]{inputenc}
\\usepackage[T2A]{fontenc}
\\usepackage[russian]{babel}
\\usepackage{amsmath, amssymb, amsfonts}
\\usepackage{graphicx}
\\usepackage{hyperref}

\\usetheme{Madrid}
\\usecolortheme{default}

\\title{Название презентации}
\\author{Иван Иванов}
\\institute{Название организации}
\\date{\\today}

\\begin{document}

\\begin{frame}
\\titlepage
\\end{frame}

\\begin{frame}{Содержание}
\\tableofcontents
\\end{frame}

\\section{Введение}
\\begin{frame}{Введение}
\\begin{itemize}
    \\item Актуальность
    \\item Цели и задачи
    \\item Ожидаемые результаты
\\end{itemize}
\\end{frame}

\\section{Основная часть}
\\begin{frame}{Ключевые идеи}
\\begin{block}{Определение}
Основное понятие.
\\end{block}

\\begin{alertblock}{Важно}
Важная информация.
\\end{alertblock}

\\begin{exampleblock}{Пример}
Пример применения.
\\end{exampleblock}
\\end{frame}

\\begin{frame}{Формулы}
\\begin{equation}
\\int_{-\\infty}^{\\infty} e^{-x^2} dx = \\sqrt{\\pi}
\\end{equation}
\\end{frame}

\\begin{frame}{Визуализация}
\\begin{figure}
\\centering
\\includegraphics[width=0.6\\textwidth]{example-image}
\\caption{График}
\\end{figure}
\\end{frame}

\\section{Результаты}
\\begin{frame}{Результаты}
\\begin{table}
\\begin{tabular}{|l|c|}
\\hline
Показатель & Значение \\\\
\\hline
A & 95\\% \\\\
B & 87\\% \\\\
\\hline
\\end{tabular}
\\end{table}
\\end{frame}

\\section{Заключение}
\\begin{frame}{Выводы}
\\begin{enumerate}
    \\item Вывод 1
    \\item Вывод 2
    \\item Вывод 3
\\end{enumerate}
\\end{frame}

\\begin{frame}{Спасибо за внимание!}
\\centering
\\Huge Спасибо! \\\\
\\large \\texttt{email@example.com}
\\end{frame}

\\end{document}`;

const LECTURE_NOTES_TEMPLATE = `\\documentclass[12pt,a4paper]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T2A]{fontenc}
\\usepackage[russian]{babel}
\\usepackage{amsmath, amssymb, amsfonts}
\\usepackage{graphicx}
\\usepackage{geometry}
\\geometry{top=1.5cm, bottom=1.5cm, left=2cm, right=2cm}
\\usepackage{tcolorbox}
\\usepackage{enumitem}
\\usepackage{hyperref}
\\usepackage{fancyhdr}
\\pagestyle{fancy}
\\fancyhead[L]{\\leftmark}
\\fancyhead[R]{\\thepage}
\\renewcommand{\\headrulewidth}{0.4pt}

\\newtcolorbox{definition}{
    colback=blue!5!white,
    colframe=blue!75!black,
    title=Определение
}

\\newtcolorbox{theorem}{
    colback=green!5!white,
    colframe=green!75!black,
    title=Теорема
}

\\newtcolorbox{example}{
    colback=yellow!5!white,
    colframe=yellow!75!black,
    title=Пример
}

\\title{\\textbf{Конспект: Название предмета}}
\\author{Автор: \\underline{\\hspace{5cm}}}
\\date{Семестр: \\underline{\\hspace{3cm}}}

\\begin{document}

\\maketitle
\\tableofcontents
\\newpage

\\section{Введение}
Общая информация о предмете.

\\subsection{Основные понятия}

\\begin{definition}
Определение ключевого термина.
\\end{definition}

\\begin{theorem}
Формулировка теоремы.
\\end{theorem}

\\begin{example}
Пример применения.
\\end{example}

\\subsection{Важные формулы}

\\begin{equation}
\\boxed{E = mc^2}
\\end{equation}

\\subsection{Ключевые выводы}
\\begin{itemize}
    \\item Пункт 1
    \\item Пункт 2
    \\item Пункт 3
\\end{itemize}

\\section{Тема 1}
Содержание раздела.

\\subsection{Подтема 1.1}
Детали.

\\subsection{Подтема 1.2}
Дополнительная информация.

\\begin{figure}[h]
\\centering
\\includegraphics[width=0.6\\textwidth]{example-image}
\\caption{Иллюстрация}
\\end{figure}

\\section{Тема 2}
Содержание раздела.

\\section*{Заключение}
Итоги конспекта.

\\end{document}`;

const TEMPLATES = [
    { name: 'Lab Work', description: 'Laboratory work with code blocks and figures', icon: Beaker, color: 'text-blue-500', bg: 'bg-blue-50 dark:bg-blue-900/20', code: LAB_WORK_TEMPLATE },
    { name: 'Scientific Article', description: 'Two-column article with formulas and bibliography', icon: BookOpen, color: 'text-purple-500', bg: 'bg-purple-50 dark:bg-purple-900/20', code: SCIENTIFIC_ARTICLE_TEMPLATE },
    { name: 'VAK Article', description: 'Full VAK article with Russian/English abstracts', icon: GraduationCap, color: 'text-emerald-500', bg: 'bg-emerald-50 dark:bg-emerald-900/20', code: VAK_ARTICLE_TEMPLATE },
    { name: 'Presentation', description: 'Beamer presentation with sections and formulas', icon: Presentation, color: 'text-orange-500', bg: 'bg-orange-50 dark:bg-orange-900/20', code: PRESENTATION_TEMPLATE },
    { name: 'Lecture Notes', description: 'Notes with definitions, theorems, examples', icon: PenTool, color: 'text-rose-500', bg: 'bg-rose-50 dark:bg-rose-900/20', code: LECTURE_NOTES_TEMPLATE },
];

export const TemplatesPanel: React.FC<TemplatesPanelProps> = ({ onInsertCode, onClose }) => {
    return (
        <>
            <div className="fixed inset-0 bg-black/20 z-40 animate-fade-in" onClick={onClose}></div>

            <div className="fixed right-0 top-0 h-full w-80 bg-gradient-to-b from-slate-300 via-blue-300 to-indigo-300 dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950 border-l border-gray-200 dark:border-gray-700 shadow-2xl z-50 overflow-y-auto animate-slide-in">
                {/* Header */}
                <div className="sticky top-0 bg-gradient-to-r from-slate-400 via-blue-400 to-indigo-400 dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950 p-4 z-10">
                    <div className="flex items-center justify-between">
                        <h2 className="text-lg font-bold text-white flex items-center gap-2">
                            <FileText className="w-5 h-5" />
                            Templates
                        </h2>
                        <button onClick={onClose} className="p-1.5 hover:bg-white/20 rounded-lg transition-colors">
                            <X className="w-5 h-5 text-white" />
                        </button>
                    </div>
                    <p className="text-white/80 dark:text-gray-400 text-xs mt-1">Click a template to insert into editor</p>
                </div>

                <div className="p-4 space-y-3">
                    {TEMPLATES.map((tpl, idx) => {
                        const Icon = tpl.icon;
                        return (
                            <div
                                key={idx}
                                className="group border border-gray-200 dark:border-gray-700 rounded-xl p-4 hover:shadow-lg hover:border-blue-300 dark:hover:border-blue-600 transition-all cursor-pointer bg-white dark:bg-gray-800"
                                onClick={() => onInsertCode(tpl.code)}
                            >
                                <div className="flex items-start gap-3 mb-3">
                                    <div className={`w-10 h-10 ${tpl.bg} rounded-xl flex items-center justify-center flex-shrink-0`}>
                                        <Icon className={`w-5 h-5 ${tpl.color}`} />
                                    </div>
                                    <div>
                                        <h3 className="font-semibold text-sm text-gray-900 dark:text-white">{tpl.name}</h3>
                                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{tpl.description}</p>
                                    </div>
                                </div>
                                <button
                                    onClick={(e) => { e.stopPropagation(); onInsertCode(tpl.code); }}
                                    className="w-full py-2 text-xs font-semibold text-white bg-gradient-to-r from-blue-600 to-indigo-600 rounded-lg hover:from-blue-700 hover:to-indigo-700 transition-all shadow-md hover:shadow-lg active:scale-[0.98]"
                                >
                                    Insert Template
                                </button>
                            </div>
                        );
                    })}
                </div>
            </div>
        </>
    );
};