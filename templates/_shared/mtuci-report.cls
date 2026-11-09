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
% Рисунок до 2/3 страницы с подписью в три строки должен помещаться наверху листа:
% при обычных 0,7 высокий снимок экрана не уходил наверх следующей страницы
% и дожидался конца раздела.
\renewcommand\topfraction{.85}
\renewcommand\textfraction{.1}

% ---------------------------------------------------------------------------
% 8. Перечисления
% ---------------------------------------------------------------------------
\RequirePackage{enumitem}
% Пункт — как абзац: метка с абзацного отступа, следующие строки — от левого поля.
% Каждый следующий уровень — ещё на 1,25 см правее. Пустых строк между пунктами нет.
\setlist{nosep}
\setlist[itemize]{label=\textendash}
\setlist[itemize,1]{wide=\bbt@indent}
\setlist[itemize,2]{wide=2\bbt@indent}
\setlist[itemize,3]{wide=3\bbt@indent}
\setlist[itemize,4]{wide=4\bbt@indent}
\AddEnumerateCounter{\bbt@asbuk}{\bbt@@asbuk}{щ}
\setlist[enumerate,1]{label=\bbt@asbuk*), ref=\bbt@asbuk*), wide=\bbt@indent}
\setlist[enumerate,2]{label=\arabic*), ref=\arabic*), wide=2\bbt@indent}
\setlist[enumerate,3]{wide=3\bbt@indent}
\setlist[enumerate,4]{wide=4\bbt@indent}

% ---------------------------------------------------------------------------
% 9. Список использованных источников
% ---------------------------------------------------------------------------
% Ссылки в тексте — \cite{key} → [4], \cite[с.~132]{key} → [4, с. 132].
% Записи — «1. Иванов И. И. …» с абзацного отступа, как пункты перечисления.
\setlocalecaption{russian}{ref}{Список использованных источников}
\RequirePackage{url}
\urlstyle{same}
\newlist{bbt@bib}{enumerate}{1}
\setlist[bbt@bib]{label=\arabic*., wide=\bbt@indent}
% Как в article: запись не рвётся на странице по одной строке, длинный адрес
% не вылезает в правое поле.
\renewenvironment{thebibliography}[1]{%
  \clearpage
  \section*{\refname}%
  \begin{bbt@bib}%
  \sloppy
  \clubpenalty4000\@clubpenalty\clubpenalty
  \widowpenalty4000}%
  {\end{bbt@bib}}

% ---------------------------------------------------------------------------
% 11. Титульный лист: \bbtTitlePage
% ---------------------------------------------------------------------------
\RequirePackage{etoolbox}

% Значения из meta.tex (architecture.md 9.6). meta.tex задаёт их через \def и
% подключается после класса. Если поля нет, на листе пустое место, а не ошибка.
\providecommand*\bbtLastName{}
\providecommand*\bbtFirstName{}
\providecommand*\bbtMiddleName{}
\providecommand*\bbtShortName{}
\providecommand*\bbtFullName{}
\providecommand*\bbtGroup{}
\providecommand*\bbtFaculty{}
\providecommand*\bbtDepartment{}
\providecommand*\bbtDiscipline{}
\providecommand*\bbtYear{}
\providecommand*\bbtCity{}
% Поля шаблона лабораторной (template.yaml, T1.3).
\providecommand*\bbtLabNumber{}
\providecommand*\bbtLabTitle{}
\providecommand*\bbtVariant{}
\providecommand*\bbtTeacher{}
\providecommand*\bbtWorkType{}

% Строка титульника, которая есть, только если поле заполнено. Пустое поле — пустая
% строка той же высоты: остальное на листе не съезжает.
\newcommand\bbt@titleline[2]{\ifdefvoid{#1}{\mbox{}}{#2}\par}
% «по практической работе», если студент выбрал «Практическая работа»;
% иначе «по лабораторной работе».
\newcommand\bbt@worktype{%
  \ifdefstring{\bbtWorkType}{Практическая работа}%
    {по практической работе}{по лабораторной работе}}
% Линия для подписи.
\newcommand\bbt@signline{\rule[-2pt]{35mm}{0.4pt}}

\newcommand\bbtTitlePage{%
  \clearpage
  \thispagestyle{empty}%
  \begingroup
  \centering
  \parindent\z@
  % Шапка — пять строк, 12 pt, одинарный интервал.
  {\fontsize{12pt}{13.8pt}\selectfont
    Министерство цифрового развития, связи и массовых коммуникаций Российской Федерации\\
    Ордена Трудового Красного Знамени\\
    федеральное государственное бюджетное образовательное учреждение\\
    высшего образования\\
    «Московский технический университет связи и информатики»\par}
  \vspace{\baselineskip}
  \bbt@titleline\bbtDepartment{Кафедра «\bbtDepartment»}
  \vfill
  % Вид работы — 20 pt, полужирный; под ним строки 14 pt.
  {\fontsize{20pt}{24pt}\selectfont\bfseries ОТЧЕТ\par}
  \vspace{0.5\baselineskip}
  \bbt@worktype\ifdefvoid\bbtLabNumber{}{ №~\bbtLabNumber}\par
  \bbt@titleline\bbtDiscipline{по дисциплине «\bbtDiscipline»}
  \bbt@titleline\bbtLabTitle{на тему «\bbtLabTitle»}
  \bbt@titleline\bbtVariant{Вариант~\bbtVariant}
  \vfill
  % Студент и преподаватель — как в бланке ВКР: 12 pt, по центру; роль, линия, имя.
  {\fontsize{12pt}{20.7pt}\selectfont
    \begin{tabular}{@{}l@{\hspace{1em}}l@{\hspace{1em}}l@{}}
      Студент\ifdefvoid\bbtGroup{}{ гр.~\bbtGroup} & \bbt@signline & \bbtShortName\\
      Преподаватель & \bbt@signline & \bbtTeacher
    \end{tabular}\par}
  \vfill
  % Город и год — по центру, примерно в 60 мм от нижнего края листа
  % (нижнее поле 25 мм + 35 мм).
  \bbtCity\ifdefvoid\bbtCity{}{\ifdefvoid\bbtYear{}{ }}%
  \ifdefvoid\bbtYear{}{\bbtYear~г.}\par
  \vspace*{35mm}%
  \endgroup
  \clearpage}

% ---------------------------------------------------------------------------
% Высокоуровневые макросы (architecture.md 9.6): рисунок, листинги, таблица
% ---------------------------------------------------------------------------

% Пустая метка — без \label: несколько пустых меток дали бы предупреждения.
\newcommand\bbt@label[1]{\ifblank{#1}{}{\label{#1}}}

% \bbtScreenshot[ширина]{путь}{подпись}{метка} — рисунок «Рисунок 3.1 – подпись».
% Ширина — длина LaTeX, по умолчанию ширина текста. Рисунок не выше 2/3 страницы,
% чтобы подпись поместилась с ним на одном листе; пропорции сохраняются.
\newcommand\bbtScreenshot[4][\linewidth]{%
  \begin{figure}%
    \centering
    \includegraphics[width=#1, height=0.66\textheight, keepaspectratio]{#2}%
    \caption{#3}\bbt@label{#4}%
  \end{figure}}

% Листинги (раздел 7): Liberation Mono 12 pt, одинарный интервал, без отступа,
% без номеров строк, рамки и фона. Длинная строка переносится, продолжение —
% с небольшим отступом. Выделения ключевых слов нет, поэтому язык ни на что
% не влияет: опечатка в его названии не ломает сборку.
\lstset{
  basicstyle=\linespread{1}\fontsize{12pt}{13.8pt}\selectfont\ttfamily,
  columns=fixed,
  basewidth=0.6em,
  keepspaces=true,
  showstringspaces=false,
  tabsize=4,
  breaklines=true,
  breakatwhitespace=false,
  breakindent=2em,
  xleftmargin=\z@,
  captionpos=t,
}
% listings разбирает только символы с кодами до 255 (\lst@DefEC). Остальные —
% кириллицу, тире, «№» — XeLaTeX печатал бы мимо него, не на своём месте:
% «Сортировка """» вместо «"""Сортировка». Добавляем их в тот же список как буквы.
\ExplSyntaxOn
\tl_new:N \l__bbt_lst_chars_tl
\cs_new_protected:Npn \__bbt_lst_char:n #1
  { \tl_put_right:Ne \l__bbt_lst_chars_tl { \char_generate:nn {#1} {12} } }
% Блоки Unicode, которые встречаются в коде студентов: латиница с диакритикой,
% греческие буквы, вся кириллица (в том числе і ї є ў), тире и кавычки, знаки валют
% (₽ €), «№» и «™», стрелки, математические знаки, рамки и фигуры (вывод дерева
% «└──»), галочки ✓ ✗.
\clist_map_inline:nn
  {
    { "0100 } { "017F }, { "0370 } { "03FF }, { "0400 } { "04FF },
    { "2010 } { "205E }, { "20A0 } { "20C0 }, { "2100 } { "214F },
    { "2190 } { "21FF }, { "2200 } { "22FF }, { "2500 } { "25FF },
    { "2713 } { "2718 }
  }
  { \int_step_function:nnN #1 \__bbt_lst_char:n }
\cs_set_eq:NN \bbt@lst@DefEC \lst@DefEC
\cs_set:Npe \lst@DefEC
  {
    \exp_not:N \bbt@lst@DefEC
    \exp_not:N \lst@CCECUse \exp_not:N \lst@ProcessLetter
    \exp_not:V \l__bbt_lst_chars_tl
    \char_generate:nn { 0 } { 12 }
  }
\ExplSyntaxOff

% \bbtCodeFile[язык]{путь}{подпись}{метка} — листинг из файла.
\newcommand\bbtCodeFile[4][]{%
  \lstinputlisting[caption={#3}, label={#4}]{#2}}

% Окружение bbtcode{язык}{подпись}{метка} — листинг текстом. Код — со следующей строки.
\lstnewenvironment{bbtcode}[3]{\lstset{caption={#2}, label={#3}}}{}

% Окружение bbttable{подпись}{метка}, внутри — обычный tabular (раздел 5).
% Таблица набирается через longtable и может перейти на следующую страницу:
% там над ней слева «Продолжение таблицы 3.2» и снова шапка — первая строка таблицы
% вместе с линиями под ней. Подпись — 14 pt, сама таблица — 12 pt, одинарный интервал.
% Таблица стоит там, где написана, по центру; подпись — у левого поля.
\RequirePackage{longtable}
\ExplSyntaxOn
\tl_new:N \l__bbt_table_tl
\tl_new:N \l__bbt_head_tl
\tl_new:N \l__bbt_rows_tl
\tl_new:N \l__bbt_caption_tl
\tl_new:N \l__bbt_label_tl
\seq_new:N \l__bbt_match_seq
\cs_generate_variant:Nn \regex_extract_once:NnN { NV }
\regex_const:Nn \c__bbt_begin_regex { \c{begin} \cB\{ tabular \cE\} }
\regex_const:Nn \c__bbt_end_regex { \A (.*) \c{end} \cB\{ tabular \cE\} }
\regex_const:Nn \c__bbt_mark_regex { \c{q_mark} }
\regex_const:Nn \c__bbt_tail_regex { \c{q_mark} \s* \c{\\} \s* \Z }
% Звёздочка и отступ после \\ шапки: «\\*», «\\[3pt]».
\regex_const:Nn \c__bbt_rowopt_regex { \A \s* \*? \s* (?: \[ [^\]]* \] )? }

\NewDocumentEnvironment { bbttable } { m m +b }
  {
    \par
    \tl_set:Nn \l__bbt_caption_tl {#1}
    \tl_set:Nn \l__bbt_label_tl {#2}
    \tl_set:Nn \l__bbt_table_tl {#3}
    % Первый \begin{tabular} и последний \end{tabular}: вложенные таблицы в ячейках
    % остаются обычными.
    \regex_replace_once:NnNTF
      \c__bbt_begin_regex { \c{bbt@tabular} } \l__bbt_table_tl
      {
        \regex_replace_once:NnN
          \c__bbt_end_regex { \1 \c{bbt@endtabular} } \l__bbt_table_tl
        \group_begin:
          % Подпись шириной в текст, у левого поля. Задаётся здесь, а не в преамбуле:
          % там ширина текста ещё не та, что после geometry.
          \setlength \LTcapwidth { \linewidth }
          \fontsize{12pt}{13.8pt}\selectfont
          \tl_use:N \l__bbt_table_tl
        \group_end:
      }
      {
        % Внутри не tabular — подпись над содержимым как есть, без переноса шапки.
        \captionof{table}{#1}\bbt@label{#2}
        #3
      }
    \par
  }
  { }

% \begin{tabular}[положение]{колонки} строки \end{tabular} внутри bbttable.
\NewDocumentCommand \bbt@tabular { O{c} m } { \__bbt_tabular:nw {#2} }
\cs_new_protected:Npn \__bbt_tabular:nw #1 #2 \bbt@endtabular
  {
    \tl_clear:N \l__bbt_head_tl
    \tl_clear:N \l__bbt_rows_tl
    \__bbt_split_head:w #2 \q_mark \\ \q_stop
    \__bbt_take_rules:
    \__bbt_longtable:nVV {#1} \l__bbt_head_tl \l__bbt_rows_tl
  }
% Шапка — всё до первого \\ (вне фигурных скобок). Метка \q_mark \\ в конце нужна,
% чтобы таблица из одной строки тоже разбиралась; после разбора она убирается.
\cs_new_protected:Npn \__bbt_split_head:w #1 \\ #2 \q_stop
  {
    \tl_set:Nn \l__bbt_head_tl { #1 \\ }
    \tl_set:Nn \l__bbt_rows_tl {#2}
    \regex_replace_once:NnN \c__bbt_mark_regex { } \l__bbt_head_tl
    \regex_replace_once:NnN \c__bbt_tail_regex { } \l__bbt_rows_tl
    \regex_extract_once:NVN \c__bbt_rowopt_regex \l__bbt_rows_tl \l__bbt_match_seq
    \tl_put_right:Ne \l__bbt_head_tl { \seq_item:Nn \l__bbt_match_seq { 1 } }
    \regex_replace_once:NnN \c__bbt_rowopt_regex { } \l__bbt_rows_tl
  }
% Линии сразу после первой строки (\hline, \cline{..}) тоже относятся к шапке.
\cs_new_protected:Npn \__bbt_take_rules:
  {
    \tl_trim_spaces:N \l__bbt_rows_tl
    \tl_if_head_eq_meaning:VNTF \l__bbt_rows_tl \hline
      {
        \tl_put_right:Nn \l__bbt_head_tl { \hline }
        \tl_set:Ne \l__bbt_rows_tl { \tl_tail:N \l__bbt_rows_tl }
        \__bbt_take_rules:
      }
      {
        \tl_if_head_eq_meaning:VNT \l__bbt_rows_tl \cline
          {
            \tl_put_right:Ne \l__bbt_head_tl
              { \exp_not:N \cline { \tl_item:Nn \l__bbt_rows_tl { 2 } } }
            \tl_set:Ne \l__bbt_rows_tl
              { \tl_range:Nnn \l__bbt_rows_tl { 3 } { -1 } }
            \__bbt_take_rules:
          }
      }
  }
\cs_generate_variant:Nn \tl_if_head_eq_meaning:nNTF { V }
\cs_generate_variant:Nn \tl_if_head_eq_meaning:nNT { V }
\cs_new_protected:Npn \__bbt_longtable:nnn #1 #2 #3
  {
    \begin{longtable}{#1}
      \exp_args:NV \caption \l__bbt_caption_tl
      \exp_args:NV \bbt@label \l__bbt_label_tl \\
      #2
    \endfirsthead
      \caption*{Продолжение~таблицы~\thetable} \\
      #2
    \endhead
      #3
    \end{longtable}
  }
\cs_generate_variant:Nn \__bbt_longtable:nnn { nVV }
\ExplSyntaxOff

\endinput
