% Общий класс учебных отчётов МТУСИ.
% Все значения — из docs/requirements/report-formatting.md (номер раздела указан у каждого
% блока). Справочник для авторов шаблонов и агента — docs/templates.md.
%
% Совместимость: макросы класса только добавляются. Существующие не переименовываются
% и не меняют поведение — иначе старые проекты соберутся по-другому (architecture.md 7).
% Служебные имена — с @ (\bbt@...): так они не совпадут с макросами полей шаблона
% \bbt<Key> из meta.tex (architecture.md 9.6).
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{mtuci-report}[2026/11/09 v1.0 MTUCI student report]

\ProcessOptions\relax
% extarticle — article с кеглем 14 pt.
\LoadClass[a4paper,14pt,oneside]{extarticle}

% ---------------------------------------------------------------------------
% 1. Страница и текст
% ---------------------------------------------------------------------------

% Поля МВКР 7.3. Колонтитулы — в полях, высота текста ровно 297 − 20 − 25 = 252 мм.
\RequirePackage[a4paper, left=30mm, right=10mm, top=20mm, bottom=25mm]{geometry}

% Liberation Serif совпадает по метрикам с Times New Roman (architecture.md 6).
\RequirePackage{fontspec}
\setmainfont{Liberation Serif}
\setsansfont{Liberation Sans}
\setmonofont{Liberation Mono}
% Символа нет в шрифте — предупреждение в логе, а не молча пустое место.
\tracinglostchars=2

% Русский язык: переносы, подписи, кавычки.
\RequirePackage[russian]{babel}

% Полуторный интервал (толкование в разделе 1): шаг строк как в Word для 14 pt —
% 14 × 1,15 × 1,5 = 24,15 pt. При высоте текста 252 мм на странице 30 строк.
% Отбивка формул — по пустой строке сверху и снизу (раздел 6).
\renewcommand\normalsize{%
  \@setfontsize\normalsize\@xivpt{24.15}%
  \abovedisplayskip 24.15\p@
  \abovedisplayshortskip \abovedisplayskip
  \belowdisplayskip \abovedisplayskip
  \belowdisplayshortskip \abovedisplayskip
  \let\@listi\@listI}
\normalsize

% Абзацный отступ 1,25 см везде, в том числе у первого абзаца после заголовка.
% Отдельная величина нужна там, где \parindent обнулён (заголовки, подписи).
\newlength\bbt@indent
\setlength\bbt@indent{1.25cm}
\setlength\parindent{\bbt@indent}
\RequirePackage{indentfirst}
% Без отступов между абзацами.
\setlength\parskip{\z@}
% Выравнивание по ширине без вылезающих за поле строк: если строку не разбить
% красиво, TeX лучше чуть растянет пробелы, чем залезет в правое поле.
\setlength\emergencystretch{2em}
% Страница не растягивается по высоте ради ровного низа: отбивки остаются точными.
\raggedbottom
% При неровном низе TeX рвёт страницу там, где ему «доплачивают», — перед заголовком
% или списком, даже если лист заполнен наполовину. Без доплат лист заполняется до низа.
\@secpenalty\z@
\@beginparpenalty\z@
\@endparpenalty\z@
\@itempenalty\z@

% ---------------------------------------------------------------------------
% 3. Нумерация страниц: арабские цифры внизу по центру, без точки.
% ---------------------------------------------------------------------------
\pagestyle{plain}

% ---------------------------------------------------------------------------
% Нумерация по разделам: рисунки, таблицы, формулы, листинги (разделы 4–7, 10)
% ---------------------------------------------------------------------------

% Буквы приложений и пунктов перечислений: без Ё, З, Й, О, Ч, Ъ, Ы, Ь (разделы 8, 10).
\def\bbt@Asbuk#1{\expandafter\bbt@@Asbuk\csname c@#1\endcsname}
\def\bbt@@Asbuk#1{\ifcase#1\or А\or Б\or В\or Г\or Д\or Е\or Ж\or И\or К\or Л\or М%
  \or Н\or П\or Р\or С\or Т\or У\or Ф\or Х\or Ц\or Ш\or Щ\or Э\or Ю\or Я\else\@ctrerr\fi}
\def\bbt@asbuk#1{\expandafter\bbt@@asbuk\csname c@#1\endcsname}
\def\bbt@@asbuk#1{\ifcase#1\or а\or б\or в\or г\or д\or е\or ж\or и\or к\or л\or м%
  \or н\or п\or р\or с\or т\or у\or ф\or х\or ц\or ш\or щ\or э\or ю\or я\else\@ctrerr\fi}

% Первая часть номера: номер раздела («3.1»), в приложении — его буква («А.1»),
% а внутри подраздела приложения — номер подраздела («А.1.2», раздел 10).
\newcommand\bbt@prefix{\thesection}
\RequirePackage{amsmath}
\RequirePackage{listings}
\newcommand\bbt@numberbysection[1]{%
  \@addtoreset{#1}{section}%
  \expandafter\def\csname the#1\endcsname{\bbt@prefix.\arabic{#1}}}
\bbt@numberbysection{figure}
\bbt@numberbysection{table}
\bbt@numberbysection{equation}
% Счётчик листингов listings создаёт в начале документа.
\AtBeginDocument{\bbt@numberbysection{lstlisting}}

% ---------------------------------------------------------------------------
% 2. Заголовки
% ---------------------------------------------------------------------------
\RequirePackage{titlesec}
\setcounter{secnumdepth}{3}

% Полужирный 14 pt, слова не переносятся. Строки заголовка не растягиваются.
\newcommand\bbt@headingfont{%
  \normalfont\normalsize\bfseries\hyphenpenalty\@M\exhyphenpenalty\@M}
% Отбивка «три интервала» — ≈17 мм (48 pt) пустого места между заголовком и текстом,
% между заголовками раздела и подраздела и перед заголовком посреди текста.
% Значение — расстояние между строками сверх обычного шага, подобрано по PDF:
% от низа букв одной строки до верха прописных следующей выходит ≈17 мм.
\newcommand\bbt@headingskip{33pt}

% «1 Цель работы»: с абзацного отступа, номер без точки. Так же подразделы «3.1»
% и пункты «3.1.2». Вторая строка длинного заголовка — от левого поля.
\titleformat{\section}[block]{\bbt@headingfont\raggedright}%
  {\hspace*{\bbt@indent}\thesection}{0.5em}{}
\titleformat{\subsection}[block]{\bbt@headingfont\raggedright}%
  {\hspace*{\bbt@indent}\thesubsection}{0.5em}{}
\titleformat{\subsubsection}[block]{\bbt@headingfont\raggedright}%
  {\hspace*{\bbt@indent}\thesubsubsection}{0.5em}{}
% Без номера (СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ, СОДЕРЖАНИЕ, ВВЕДЕНИЕ): прописными
% по центру. Прописными делает класс: автор пишет \section*{Введение}.
\titleformat{name=\section,numberless}[block]{\bbt@headingfont\centering}{}{0pt}%
  {\MakeUppercase}
% Без звёздочки: первый абзац после заголовка — с отступом, как остальные.
\titlespacing{\section}{\z@}{\bbt@headingskip}{\bbt@headingskip}
\titlespacing{\subsection}{\z@}{\bbt@headingskip}{\bbt@headingskip}
\titlespacing{\subsubsection}{\z@}{\bbt@headingskip}{\bbt@headingskip}

% Разделы лабораторной идут подряд, без новой страницы (раздел 2, исключение).
% С новой страницы — список источников и каждое приложение (разделы 9, 10).
% Рисунки не уходят за границу своего раздела: перед разделом выводятся все,
% что ждут места.
\RequirePackage{placeins}
\newif\ifbbt@appendix
\let\bbt@titlesec@section\section
\renewcommand\section{%
  \ifbbt@appendix\clearpage\else\FloatBarrier\fi
  \bbt@titlesec@section}

% ---------------------------------------------------------------------------
% 10. Приложения: \appendix, затем \section{Название} на каждое приложение.
% ---------------------------------------------------------------------------
% «Приложение А» вверху по центру, на следующей строке по центру — название.
\renewcommand\appendix{%
  \par
  \global\bbt@appendixtrue
  \setcounter{section}{0}%
  \gdef\thesection{\bbt@Asbuk{section}}%
  \gdef\bbt@prefix{\ifnum\c@subsection>\z@\thesubsection\else\thesection\fi}%
  \@addtoreset{figure}{subsection}%
  \@addtoreset{table}{subsection}%
  \@addtoreset{equation}{subsection}%
  \@addtoreset{lstlisting}{subsection}%
  \titleformat{\section}[display]{\bbt@headingfont\centering}%
    {\appendixname~\thesection}{\z@}{}%
  \titlespacing{\section}{\z@}{\z@}{\bbt@headingskip}}

% ---------------------------------------------------------------------------
% 4, 5, 7. Подписи: «Рисунок 3.1 – Название», «Таблица 3.2 – …», «Листинг 3.1 – …»
% ---------------------------------------------------------------------------
\RequirePackage{graphicx}
\RequirePackage{caption}
% Короткое тире с пробелами; номер не отрывается от тире переносом строки.
\DeclareCaptionLabelSeparator{bbt}{\nobreakspace\textendash\space}
\captionsetup{labelsep=bbt, font=normalsize, labelfont={}, textfont={}}
% Рисунок: подпись под ним по центру.
\captionsetup[figure]{position=below, justification=centering, skip=12pt}
% Таблица и листинг: подпись над ними, слева, без абзацного отступа.
\captionsetup[table]{position=above, justification=raggedright,
  singlelinecheck=false, skip=6pt}
\captionsetup[lstlisting]{position=above, justification=raggedright,
  singlelinecheck=false, skip=6pt}
\setlocalecaption{russian}{figure}{Рисунок}
\renewcommand\lstlistingname{Листинг}

% Рисунок — сразу после ссылки, если на странице есть место; иначе наверху следующей.
% flafter не даёт рисунку встать выше места, где он написан в тексте.
\RequirePackage{flafter}
\def\fps@figure{ht}
\def\fps@table{ht}

% ---------------------------------------------------------------------------
% 8. Перечисления
% ---------------------------------------------------------------------------
\RequirePackage{enumitem}
% Пункт — как абзац: метка с абзацного отступа, следующие строки — от левого поля.
% Пустых строк между пунктами нет.
\setlist{nosep}
\setlist[itemize]{label=\textendash, wide=2\parindent}
\setlist[itemize,1]{wide=\parindent}
\AddEnumerateCounter{\bbt@asbuk}{\bbt@@asbuk}{щ}
\setlist[enumerate,1]{label=\bbt@asbuk*), ref=\bbt@asbuk*), wide=\parindent}
\setlist[enumerate,2]{label=\arabic*), ref=\arabic*), wide=2\parindent}

% ---------------------------------------------------------------------------
% 9. Список использованных источников
% ---------------------------------------------------------------------------
% Ссылки в тексте — \cite{key} → [4], \cite[с.~132]{key} → [4, с. 132].
% Записи — «1. Иванов И. И. …» с абзацного отступа, как пункты перечисления.
\setlocalecaption{russian}{ref}{Список использованных источников}
\RequirePackage{url}
\urlstyle{same}
\newlist{bbt@bib}{enumerate}{1}
\setlist[bbt@bib]{label=\arabic*., wide=\parindent}
\renewenvironment{thebibliography}[1]{%
  \clearpage
  \section*{\refname}%
  \begin{bbt@bib}}%
  {\end{bbt@bib}}

\endinput
