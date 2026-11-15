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
% Моноширинный текст в абзаце (\texttt) — по высоте строчных букв основного шрифта:
% Liberation Mono того же кегля заметно крупнее Liberation Serif (раздел 1).
\setmonofont{Liberation Mono}[Scale=MatchLowercase]
% Листинги — тот же шрифт без масштаба: их размер задан точно (раздел 7).
\newfontfamily\bbt@codefont{Liberation Mono}[NFSSFamily=bbtcode, Ligatures=TeXOff]
% Символа нет в шрифте — предупреждение в логе, а не молча пустое место.
\tracinglostchars=2
% Переносы в моноширинном тексте абзаца — после «. , ( ) [ ] / = : ; _», без дефиса.
% Иначе \texttt{rng.randrange(lo, hi + 1)} не переносится и вылезает за поле. XeTeX
% вставляет \allowbreak между таким знаком и следующей буквой или цифрой, только внутри
% \texttt. Между двумя такими знаками разрыва нет: «()» и «).» не рвутся, и строка
% не начинается с одинокой «)».
\newXeTeXintercharclass\bbt@ttbreakclass
\XeTeXinterchartoks\bbt@ttbreakclass\z@={\allowbreak}
\newcommand\bbt@ttbreaks{%
  \XeTeXinterchartokenstate\@ne
  \XeTeXcharclass`\.=\bbt@ttbreakclass \XeTeXcharclass`\,=\bbt@ttbreakclass
  \XeTeXcharclass`\(=\bbt@ttbreakclass \XeTeXcharclass`\)=\bbt@ttbreakclass
  \XeTeXcharclass`\[=\bbt@ttbreakclass \XeTeXcharclass`\]=\bbt@ttbreakclass
  \XeTeXcharclass`\/=\bbt@ttbreakclass \XeTeXcharclass`\==\bbt@ttbreakclass
  \XeTeXcharclass`\:=\bbt@ttbreakclass \XeTeXcharclass`\;=\bbt@ttbreakclass
  \XeTeXcharclass`\_=\bbt@ttbreakclass}
\DeclareTextFontCommand{\texttt}{\ttfamily\bbt@ttbreaks}

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
% Нумерация рисунков, таблиц, формул и листингов (разделы 4–7, 10): сквозная по работе —
% «Рисунок 1», «(2)»; в приложении — с его буквой, «Рисунок А.1»
% ---------------------------------------------------------------------------

% Буквы приложений и пунктов перечислений: без Ё, З, Й, О, Ч, Ъ, Ы, Ь (разделы 8, 10).
\def\bbt@Asbuk#1{\expandafter\bbt@@Asbuk\csname c@#1\endcsname}
\def\bbt@@Asbuk#1{\ifcase#1\or А\or Б\or В\or Г\or Д\or Е\or Ж\or И\or К\or Л\or М%
  \or Н\or П\or Р\or С\or Т\or У\or Ф\or Х\or Ц\or Ш\or Щ\or Э\or Ю\or Я\else\@ctrerr\fi}
\def\bbt@asbuk#1{\expandafter\bbt@@asbuk\csname c@#1\endcsname}
\def\bbt@@asbuk#1{\ifcase#1\or а\or б\or в\or г\or д\or е\or ж\or и\or к\or л\or м%
  \or н\or п\or р\or с\or т\or у\or ф\or х\or ц\or ш\or щ\or э\or ю\or я\else\@ctrerr\fi}

% В основной части номера сквозные: счётчики article не сбрасываются по разделам.
% В приложении первая часть номера — его буква («А.1»), а внутри подраздела
% приложения — номер подраздела («А.1.2», раздел 10). Счётчик листингов listings
% создаёт в начале документа, а \appendix стоит в документе — он уже есть.
\newcommand\bbt@prefix{\thesection}
\RequirePackage{amsmath}
\RequirePackage{listings}
\newcommand\bbt@numberbyappendix[1]{%
  \@addtoreset{#1}{section}%
  \@addtoreset{#1}{subsection}%
  \expandafter\gdef\csname the#1\endcsname{\bbt@prefix.\arabic{#1}}}

% ---------------------------------------------------------------------------
% 2. Заголовки
% ---------------------------------------------------------------------------
\RequirePackage{titlesec}
\setcounter{secnumdepth}{3}

% Полужирный 14 pt, слова не переносятся. Строки заголовка не растягиваются.
\newcommand\bbt@headingfont{%
  \normalfont\normalsize\bfseries\hyphenpenalty\@M\exhyphenpenalty\@M}
% Отбивка лабораторной (раздел 2): над заголовком посреди текста — одна пустая строка
% (шаг строки сверх обычного), под заголовком — половина: заголовок ближе к своему
% тексту, чем к предыдущему. Под заголовком раздела, за которым сразу идёт подраздел, —
% тоже половина: titlesec не добавляет над заголовком отбивку, если выше заголовок.
\newcommand\bbt@headingskip{24.15pt}
\newcommand\bbt@afterheadingskip{12pt}

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
\titlespacing{\section}{\z@}{\bbt@headingskip}{\bbt@afterheadingskip}
\titlespacing{\subsection}{\z@}{\bbt@headingskip}{\bbt@afterheadingskip}
\titlespacing{\subsubsection}{\z@}{\bbt@headingskip}{\bbt@afterheadingskip}

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
  \bbt@numberbyappendix{figure}%
  \bbt@numberbyappendix{table}%
  \bbt@numberbyappendix{equation}%
  \bbt@numberbyappendix{lstlisting}%
  \titleformat{\section}[display]{\bbt@headingfont\centering}%
    {\appendixname~\thesection}{\z@}{}%
  \titlespacing{\section}{\z@}{\z@}{\bbt@headingskip}}

% ---------------------------------------------------------------------------
% 4, 5, 7. Подписи: «Рисунок 1 – Название», «Таблица 2 – …», «Листинг 1 – …»
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
% Ссылка на пункт — буква или номер без скобки: «(пункт~\ref{…})» → «(пункт в)».
\setlist[enumerate,1]{label=\bbt@asbuk*), ref=\bbt@asbuk*, wide=\bbt@indent}
\setlist[enumerate,2]{label=\arabic*), ref=\arabic*, wide=2\bbt@indent}
\setlist[enumerate,3]{wide=3\bbt@indent}
\setlist[enumerate,4]{wide=4\bbt@indent}

% Окружение bbttask[нумерация] — пункты задания с номерами из методички (раздел 8):
% по умолчанию «1)», «2)»; [а] — «а)», «б)» (латинская «a» — то же самое: на вид
% их не отличить). \item[5] — пункт с номером из методички, если варианту достались
% не все пункты; следующий \item продолжит с 6. Ссылка — номер без скобки, «(пункт 5)».
% Вложенный enumerate — буквами, если задание пронумеровано цифрами, иначе цифрами.
% Регистр буквы не важен: [А] — тоже «а)».
\ExplSyntaxOn
\tl_new:N \l__bbt_task_depth_tl
% \item ядра — копия до переопределения: вложенный bbttask не должен вызывать \item
% внешнего, иначе \item вызывает сам себя и сборка зависает.
\cs_new_eq:NN \__bbt_task_item: \item
\NewDocumentEnvironment { bbttask } { O{1} }
  {
    \str_case_e:nnF { \text_lowercase:n { \tl_trim_spaces:n {#1} } }
      {
        { а } { \__bbt_task_begin:n { \bbt@asbuk* } }
        { a } { \__bbt_task_begin:n { \bbt@asbuk* } }
        { 1 } { \__bbt_task_begin:n { \arabic* } }
      }
      {
        \ClassWarning { mtuci-report }
          { bbttask:~нумерация~«\tl_to_str:n {#1}»~неизвестна,~пункты~—~цифрами }
        \__bbt_task_begin:n { \arabic* }
      }
  }
  { \end{enumerate} }
\cs_new_protected:Npn \__bbt_task_begin:n #1
  {
    \tl_if_eq:nnT {#1} { \arabic* }
      {
        % \setlist заменяет настройки уровня целиком — отступ повторяется.
        \setlist [ enumerate, 2 ]
          { label = \bbt@asbuk*), ref = \bbt@asbuk*, wide = 2\bbt@indent }
      }
    \begin{enumerate} [ label = #1), ref = #1 ]
    \tl_set:Ne \l__bbt_task_depth_tl { \int_use:N \@listdepth }
    \cs_set_protected:Npn \item
      {
        \int_compare:nNnTF { \@listdepth } = { \l__bbt_task_depth_tl }
          { \peek_meaning:NTF [ \__bbt_task_item:w \__bbt_task_item: }
          { \__bbt_task_item: }
      }
  }
% \item[N]: метка «N)», ссылка «N»; номер цифрами — следующий пункт будет N + 1.
% Счётчик — текущего уровня (\@enumctr): задание может стоять и внутри другого списка.
\cs_new_protected:Npn \__bbt_task_item:w [ #1 ]
  {
    \__bbt_task_item: [ #1) ]
    \tl_set:Nn \@currentlabel {#1}
    \regex_match:nnT { \A \d+ \Z } {#1} { \setcounter { \@enumctr } {#1} }
  }
\ExplSyntaxOff

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
% Кафедра, дисциплина и тема для титульника (T2.1): \bbt@department, \bbt@discipline,
% \bbt@topic. Студент часто вводит их как в методичке — тему в кавычках и с точкой,
% кафедру со словом «Кафедра». Кавычки «…» и слово «Кафедра» класс ставит сам, а точки
% в конце строки титульника нет (report-formatting.md, раздел 11). Поэтому здесь
% убираются пробелы по краям, одна точка в конце (многоточие остаётся), внешняя пара
% кавычек «…», "…", „…“ или “…”, если внутри нет таких же, а у кафедры — слово «Кафедра»
% в начале. Макросы meta.tex не меняются: чистится только то, что печатает титульник.
\ExplSyntaxOn
\tl_new:N \bbt@department
\tl_new:N \bbt@discipline
\tl_new:N \bbt@topic
\tl_new:N \l__bbt_title_tl
\tl_new:N \l__bbt_title_item_tl
\tl_new:N \l__bbt_title_inner_tl
\regex_const:Nn \c__bbt_title_department_regex { \A [Кк]афедра \s+ }
% Элемент #1 значения (отрицательный — с конца) — символ #2. Сравниваются строки:
% результат не зависит от категорий символов.
\prg_new_protected_conditional:Npnn \__bbt_title_item_if:nn #1 #2 { T , F , TF }
  {
    \tl_set:Ne \l__bbt_title_item_tl { \tl_item:Nn \l__bbt_title_tl {#1} }
    \str_if_eq:VnTF \l__bbt_title_item_tl {#2}
      { \prg_return_true: } { \prg_return_false: }
  }
\cs_new_protected:Npn \__bbt_title_drop_period:
  {
    \__bbt_title_item_if:nnT { -1 } { . }
      {
        \__bbt_title_item_if:nnF { -2 } { . }
          {
            \tl_set:Ne \l__bbt_title_tl { \tl_range:Nnn \l__bbt_title_tl { 1 } { -2 } }
            \tl_trim_spaces:N \l__bbt_title_tl
          }
      }
  }
% Внешняя пара кавычек #1…#2, если внутри нет ни #1, ни #2.
\cs_new_protected:Npn \__bbt_title_unquote:nn #1 #2
  {
    \__bbt_title_item_if:nnT { 1 } {#1}
      {
        \__bbt_title_item_if:nnT { -1 } {#2}
          {
            \tl_set:Ne \l__bbt_title_inner_tl { \tl_range:Nnn \l__bbt_title_tl { 2 } { -2 } }
            \exp_args:NV \str_if_in:nnF \l__bbt_title_inner_tl {#1}
              {
                \exp_args:NV \str_if_in:nnF \l__bbt_title_inner_tl {#2}
                  {
                    \tl_set_eq:NN \l__bbt_title_tl \l__bbt_title_inner_tl
                    \tl_trim_spaces:N \l__bbt_title_tl
                  }
              }
          }
      }
  }
% Точка бывает и до закрывающей кавычки, и после неё.
\cs_new_protected:Npn \__bbt_title_clean:N #1
  {
    \tl_trim_spaces:N \l__bbt_title_tl
    \__bbt_title_drop_period:
    \__bbt_title_unquote:nn { « } { » }
    \__bbt_title_unquote:nn { " } { " }
    \__bbt_title_unquote:nn { „ } { “ }
    \__bbt_title_unquote:nn { “ } { ” }
    \__bbt_title_drop_period:
    \tl_set_eq:NN #1 \l__bbt_title_tl
  }
\cs_new_protected:Npn \bbt@titlevalues
  {
    \tl_set_eq:NN \l__bbt_title_tl \bbtDepartment
    \tl_trim_spaces:N \l__bbt_title_tl
    \regex_replace_once:NnN \c__bbt_title_department_regex { } \l__bbt_title_tl
    \__bbt_title_clean:N \bbt@department
    \tl_set_eq:NN \l__bbt_title_tl \bbtDiscipline
    \__bbt_title_clean:N \bbt@discipline
    \tl_set_eq:NN \l__bbt_title_tl \bbtLabTitle
    \__bbt_title_clean:N \bbt@topic
  }
\ExplSyntaxOff
% «по практической работе», если студент выбрал «Практическая работа»;
% иначе «по лабораторной работе».
\newcommand\bbt@worktype{%
  \ifdefstring{\bbtWorkType}{Практическая работа}%
    {по практической работе}{по лабораторной работе}}
% Линия для подписи.
\newcommand\bbt@signline{\rule[-2pt]{35mm}{0.4pt}}
% Блок подписей не шире строки (T2.1). Колонки роли и имени меряются целиком: если вместе
% с линией они помещаются, таблица как раньше, всё одной строкой. Если нет, сужается
% широкая колонка, и текст в ней переносится. Узкая колонка сохраняет свою ширину, если
% занимает не больше половины места, иначе обеим — по половине.
\newlength\bbt@rolewd
\newlength\bbt@namewd
\newcommand\bbt@studentrole{Студент\ifdefvoid\bbtGroup{}{ гр.~\bbtGroup}}
% \bbt@widen{длина}{текст}: длина — не меньше ширины текста.
\newcommand\bbt@widen[2]{%
  \settowidth\@tempdima{#2}%
  \ifdim\@tempdima>#1\setlength#1{\@tempdima}\fi}
\newcommand\bbt@fitsignatures{%
  \setlength\bbt@rolewd\z@
  \bbt@widen\bbt@rolewd{\bbt@studentrole}%
  \bbt@widen\bbt@rolewd{Преподаватель}%
  \setlength\bbt@namewd\z@
  \bbt@widen\bbt@namewd{\bbtShortName}%
  \bbt@widen\bbt@namewd{\bbtTeacher}%
  % Место под роль и имя: строка без линии и двух отступов по 1em между колонками.
  \settowidth\@tempdimb{\bbt@signline}%
  \setlength\@tempdimb{\dimexpr\linewidth-\@tempdimb-2em\relax}%
  \ifdim\dimexpr\bbt@rolewd+\bbt@namewd\relax>\@tempdimb
    \ifdim\bbt@rolewd>.5\@tempdimb
      \ifdim\bbt@namewd>.5\@tempdimb
        \setlength\bbt@rolewd{.5\@tempdimb}%
        \setlength\bbt@namewd{.5\@tempdimb}%
      \else
        \setlength\bbt@rolewd{\dimexpr\@tempdimb-\bbt@namewd\relax}%
      \fi
    \else
      \setlength\bbt@namewd{\dimexpr\@tempdimb-\bbt@rolewd\relax}%
    \fi
  \fi}
% \bbt@fitcell{ширина}{текст}: текст одной строкой, если помещается, иначе абзац этой
% ширины. Интервал внутри — одинарный, переносы — между словами и после дефиса двойной
% фамилии, но не внутри слов. Последняя строка опускает следующую строку таблицы
% на обычный шаг, как у p-колонки.
\newcommand\bbt@fitcell[2]{%
  \settowidth\@tempdima{#2}%
  \ifdim\@tempdima>#1%
    \expandafter\@firstoftwo
  \else
    \expandafter\@secondoftwo
  \fi
  {\parbox[t]{#1}{\fontsize{12pt}{13.8pt}\selectfont\raggedright\hyphenpenalty\@M
    #2\@finalstrut\@arstrutbox}}%
  {#2}}

\newcommand\bbtTitlePage{%
  \clearpage
  \thispagestyle{empty}%
  \begingroup
  \bbt@titlevalues
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
  \bbt@titleline\bbt@department{Кафедра «\bbt@department»}
  \vfill
  % Вид работы — 20 pt, полужирный; под ним строки 14 pt.
  {\fontsize{20pt}{24pt}\selectfont\bfseries ОТЧЕТ\par}
  \vspace{0.5\baselineskip}
  \bbt@worktype\ifdefvoid\bbtLabNumber{}{ №~\bbtLabNumber}\par
  \bbt@titleline\bbt@discipline{по дисциплине «\bbt@discipline»}
  \bbt@titleline\bbt@topic{на тему «\bbt@topic»}
  \bbt@titleline\bbtVariant{Вариант~\bbtVariant}
  \vfill
  % Студент и преподаватель — как в бланке ВКР: 12 pt, по центру; роль, линия, имя.
  {\fontsize{12pt}{20.7pt}\selectfont
    \bbt@fitsignatures
    \begin{tabular}{@{}l@{\hspace{1em}}l@{\hspace{1em}}l@{}}
      \bbt@fitcell\bbt@rolewd{\bbt@studentrole} & \bbt@signline &
        \bbt@fitcell\bbt@namewd{\bbtShortName}\\
      \bbt@fitcell\bbt@rolewd{Преподаватель} & \bbt@signline &
        \bbt@fitcell\bbt@namewd{\bbtTeacher}
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

% \bbtScreenshot[ширина]{путь}{подпись}{метка} — рисунок «Рисунок 1 – подпись».
% Ширина — длина LaTeX, по умолчанию ширина текста. Рисунок не выше 2/3 страницы,
% чтобы подпись поместилась с ним на одном листе; пропорции сохраняются.
\newcommand\bbtScreenshot[4][\linewidth]{%
  \begin{figure}%
    \centering
    \includegraphics[width=#1, height=0.66\textheight, keepaspectratio]{#2}%
    \caption{#3}\bbt@label{#4}%
  \end{figure}}

% Листинги (раздел 7): Liberation Mono 10 pt, одинарный интервал, без отступа и номеров
% строк, в тонкой рамке, с подсветкой синтаксиса. 10 pt — чтобы строка в 79 знаков
% (предел PEP 8) помещалась в рамку без переноса: 79 × 6 pt = 474 pt, а внутри рамки
% 481,9 − 2 × (3,4 + 0,4) = 474,3 pt. Рамка — в пределах полей. Длинная строка
% переносится; продолжение — с отступом своей строки и серой стрелкой в начале.
\RequirePackage{xcolor}
% Цвета светлой темы VS Code — самой частой у студентов. Все тёмные: на чёрно-белой
% печати код читается.
\definecolor{bbt@code@keyword}{HTML}{0000FF}
\definecolor{bbt@code@type}{HTML}{267F99}
\definecolor{bbt@code@string}{HTML}{A31515}
\definecolor{bbt@code@comment}{HTML}{008000}
\definecolor{bbt@code@break}{gray}{0.5}
% Моноширинный шрифт listings узнаёт по \ttdefault и только тогда печатает «-» и «*»
% как есть, а не знаками минус и умножение. Поэтому внутри листинга \ttdefault — это
% семейство листингов.
\lstset{
  basicstyle=\linespread{1}\fontsize{10pt}{11.5pt}\selectfont
    \bbt@codefont\let\ttdefault\f@family,
  columns=fixed,
  basewidth=0.6em,
  % Пробелы в начале строки listings считает отступом продолжения (breakautoindent),
  % только если не держит их как текст: при columns=fixed вид от этого не меняется.
  keepspaces=false,
  showstringspaces=false,
  tabsize=4,
  breaklines=true,
  breakatwhitespace=false,
  breakautoindent=true,
  breakindent=\z@,
  postbreak=\mbox{\textcolor{bbt@code@break}{$\hookrightarrow$}\space},
  frame=single,
  framerule=0.4pt,
  framesep=3.4pt,
  rulecolor=\color{black},
  xleftmargin=3.8pt,
  xrightmargin=3.8pt,
  captionpos=t,
  keywordstyle=\color{bbt@code@keyword},
  keywordstyle=[2]\color{bbt@code@type},
  keywordstyle=[3]\color{bbt@code@type},
  stringstyle=\color{bbt@code@string},
  commentstyle=\color{bbt@code@comment},
}
% Где переносить длинную строку. listings разрешает перенос после каждого слова и знака,
% и TeX рвал строку у самой границы: на новой строке оставались «;» или «)."""».
% Теперь перенос у последнего пробела, который помещается, а без пробела — где придётся:
% у разрыва после пробела непустая часть до разрыва (\kern0pt) — штраф \hyphenpenalty,
% у остальных пустая — \exhyphenpenalty, он выше.
\gdef\lst@@discretionary{%
  \discretionary{\lst@ifwhitespace\kern\z@\fi\let\space\lst@spacekern\lst@prebreak}%
    {\llap{\lsthk@EveryLine\kern\lst@breakcurrindent \kern-\@totalleftmargin}%
     \let\space\lst@spacekern\lst@postbreak}{}}
\lst@AddToHook{Init}{\hyphenpenalty\z@ \exhyphenpenalty 3000\relax}
% Подряд идущие знаки (« # -------- », «========») listings набирает одним куском,
% который не разорвать: длинная строка из них вылезала за рамку. Режем такие серии
% по 8 знаков. Короткие операторы («->», «**=») и разбор комментариев не меняются.
\let\bbt@lst@AppendOther\lst@AppendOther
\def\lst@AppendOther{%
  \lst@ifletter\else\ifnum\lst@length<8 \else\lst@OutputOther\fi\fi
  \bbt@lst@AppendOther}
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

% Языки, которых нет в listings.
\lstdefinelanguage{bbtjs}{
  morekeywords={async,await,break,case,catch,class,const,continue,debugger,default,
    delete,do,else,export,extends,finally,for,from,function,get,if,import,in,
    instanceof,let,new,of,return,set,static,super,switch,this,throw,try,typeof,var,
    void,while,with,yield,true,false,null,undefined},
  sensitive=true,
  morecomment=[l]{//},
  morecomment=[s]{/*}{*/},
  morestring=[b]",
  morestring=[b]',
  morestring=[b]`,
}
\lstdefinelanguage{bbtts}[]{bbtjs}{
  morekeywords=[2]{abstract,any,as,boolean,declare,enum,implements,interface,keyof,
    namespace,never,number,private,protected,public,readonly,string,type,unknown},
}
\lstdefinelanguage{bbtkotlin}{
  morekeywords={abstract,as,break,by,catch,class,companion,constructor,continue,data,
    do,else,enum,false,final,finally,for,fun,if,import,in,init,inline,interface,
    internal,is,lateinit,null,object,open,operator,override,package,private,
    protected,public,return,sealed,super,suspend,this,throw,true,try,typealias,val,
    var,vararg,when,while},
  sensitive=true,
  morecomment=[l]{//},
  morecomment=[s]{/*}{*/},
  morestring=[s]{"""}{"""},
  morestring=[b]",
  morestring=[b]',
}
\lstdefinelanguage{bbtrust}{
  morekeywords={as,async,await,break,const,continue,crate,dyn,else,enum,extern,false,
    fn,for,if,impl,in,let,loop,match,mod,move,mut,pub,ref,return,self,Self,static,
    struct,super,trait,true,type,unsafe,use,where,while},
  sensitive=true,
  morecomment=[l]{//},
  morecomment=[s]{/*}{*/},
  morestring=[b]",
}

% Язык подсветки: имя или расширение файла → язык listings. Имя сравнивается без
% регистра, пробелов и «\»; «#» — это sharp, «+» — p: «C\#» и «C#» → csharp,
% «C++» → cpp. Пустой язык — листинг без подсветки, но и без предупреждения.
\ExplSyntaxOn
\prop_const_from_keyval:Nn \c__bbt_code_languages_prop
  {
    % Python 3: в listings по умолчанию — Python 2 с его встроенными именами.
    python = {[3]Python}, py = {[3]Python}, python3 = {[3]Python}, pyw = {[3]Python},
    c = C, h = C,
    cpp = C++, cxx = C++, cc = C++, hpp = C++, hxx = C++, hh = C++,
    csharp = {[Sharp]C}, cs = {[Sharp]C},
    java = Java,
    javascript = bbtjs, js = bbtjs, mjs = bbtjs, cjs = bbtjs, jsx = bbtjs,
    node = bbtjs, nodejs = bbtjs,
    typescript = bbtts, ts = bbtts, tsx = bbtts,
    kotlin = bbtkotlin, kt = bbtkotlin, kts = bbtkotlin,
    rust = bbtrust, rs = bbtrust,
    go = Go, golang = Go,
    swift = Swift, scala = Scala,
    sql = SQL, mysql = SQL, postgresql = SQL, postgres = SQL, sqlite = SQL,
    plsql = SQL, tsql = SQL, psql = SQL,
    php = PHP,
    pascal = Pascal, pas = Pascal, freepascal = Pascal, lpr = Pascal,
    delphi = Delphi, dpr = Delphi, objectpascal = Delphi,
    bash = bash, sh = sh, shell = bash, zsh = bash,
    html = HTML, htm = HTML, xml = XML,
    haskell = Haskell, hs = Haskell,
    r = R,
    matlab = Matlab, m = Matlab, octave = Octave,
    ruby = Ruby, rb = Ruby, lua = {[5.3]Lua}, perl = Perl, pl = Perl,
    prolog = Prolog, lisp = Lisp, erlang = erlang, erl = erlang,
    fortran = Fortran, f90 = Fortran, f95 = Fortran, for = Fortran,
    vhdl = VHDL, vhd = VHDL, verilog = Verilog, v = Verilog,
    asm = {[x86masm]Assembler}, assembler = {[x86masm]Assembler},
    assembly = {[x86masm]Assembler}, nasm = {[x86masm]Assembler},
    masm = {[x86masm]Assembler},
    make = make, makefile = make, cmake = CMake,
    vb = {[Visual]Basic}, vbnet = {[Visual]Basic}, vbs = VBScript,
    text = {}, txt = {}, plain = {}, plaintext = {}, output = {}, console = {},
    log = {}, csv = {}, json = {}, yaml = {}, yml = {}, ini = {}, toml = {},
    css = {}, none = {}
  }
\str_const:Ne \c__bbt_two_hashes_str { \c_hash_str \c_hash_str }
\str_new:N \l__bbt_code_language_str
\str_new:N \l__bbt_code_lines_str
\str_new:N \l__bbt_code_key_str
\str_new:N \l__bbt_code_path_str
\tl_new:N \l__bbt_code_style_tl
\seq_new:N \l__bbt_code_items_seq
\seq_new:N \l__bbt_code_match_seq
\bool_new:N \l__bbt_code_found_bool

% Ключ таблицы языков из имени или расширения: #2 → #1.
\cs_new_protected:Npn \__bbt_code_key:Nn #1 #2
  {
    \str_set:Ne #1 { \str_lowercase:n {#2} }
    \regex_replace_all:nnN { [\\\s] } { } #1
    \regex_replace_all:nnN { \#+ } { sharp } #1
    \regex_replace_all:nnN { \+ } { p } #1
  }
% Найти язык по ключу #1: \l__bbt_code_style_tl и \l__bbt_code_found_bool.
\cs_new_protected:Npn \__bbt_code_lookup:N #1
  {
    \prop_get:NVNTF \c__bbt_code_languages_prop #1 \l__bbt_code_style_tl
      { \bool_set_true:N \l__bbt_code_found_bool }
      { \bool_set_false:N \l__bbt_code_found_bool }
  }
\cs_generate_variant:Nn \prop_get:NnNTF { NV }

% Подсветка листинга: язык #1 (строка), путь файла #2 (пустой у bbtcode).
% Язык неизвестен — берётся по расширению файла; не узнан и так — без подсветки,
% с предупреждением в логе. Сборка не падает ни в каком случае.
\cs_new_protected:Npn \__bbt_code_language:nn #1 #2
  {
    \bool_set_false:N \l__bbt_code_found_bool
    \tl_if_blank:nF {#1}
      {
        \__bbt_code_key:Nn \l__bbt_code_key_str {#1}
        \__bbt_code_lookup:N \l__bbt_code_key_str
      }
    \bool_if:NF \l__bbt_code_found_bool
      {
        \str_set:Nn \l__bbt_code_path_str {#2}
        \regex_extract_once:nVNT { \.([^./]+) \Z } \l__bbt_code_path_str
          \l__bbt_code_match_seq
          {
            \exp_args:NNe \__bbt_code_key:Nn \l__bbt_code_key_str
              { \seq_item:Nn \l__bbt_code_match_seq { 2 } }
            \__bbt_code_lookup:N \l__bbt_code_key_str
          }
        \tl_if_blank:nF {#1}
          {
            % Строкой «#» удваивается: «F#» → «F##». В тексте предупреждения — один.
            \str_set:Nn \l__bbt_code_key_str {#1}
            \exp_args:NNVV \str_replace_all:Nnn \l__bbt_code_key_str
              \c__bbt_two_hashes_str \c_hash_str
            \ClassWarning { mtuci-report }
              {
                Язык~листинга~«\l__bbt_code_key_str»~неизвестен:~
                \bool_if:NTF \l__bbt_code_found_bool
                  { подсветка~по~расширению~файла }
                  { листинг~без~подсветки }
              }
          }
      }
    \bool_if:NT \l__bbt_code_found_bool
      {
        \tl_if_empty:NF \l__bbt_code_style_tl
          { \exp_args:Ne \lstset { language = { \l__bbt_code_style_tl } } }
      }
  }
\cs_generate_variant:Nn \regex_extract_once:nnNT { nV }

% Необязательный аргумент \bbtCodeFile: «язык, lines=10-25» (architecture.md 9.6).
% Элемент без «=» и language=… — язык; lines=N-M или lines=N — строки файла.
% Строкой сразу: «#» в имени языка (C#) не ломает разбор.
\cs_new_protected:Npn \__bbt_code_options:nn #1 #2
  {
    \str_clear:N \l__bbt_code_language_str
    \str_clear:N \l__bbt_code_lines_str
    \seq_set_split:Nne \l__bbt_code_items_seq { , } { \tl_to_str:n {#1} }
    \seq_map_inline:Nn \l__bbt_code_items_seq
      {
        \regex_extract_once:nnNTF { \A ([^=]*) = (.*) \Z } {##1} \l__bbt_code_match_seq
          {
            \str_set:Ne \l__bbt_code_key_str
              {
                \str_lowercase:e
                  { \tl_trim_spaces:e { \seq_item:Nn \l__bbt_code_match_seq { 2 } } }
              }
            \str_case:VnF \l__bbt_code_key_str
              {
                { lines }
                  {
                    \str_set:Ne \l__bbt_code_lines_str
                      { \seq_item:Nn \l__bbt_code_match_seq { 3 } }
                  }
                { language }
                  {
                    \str_set:Ne \l__bbt_code_language_str
                      { \tl_trim_spaces:e { \seq_item:Nn \l__bbt_code_match_seq { 3 } } }
                  }
              }
              {
                \ClassWarning { mtuci-report }
                  { Ключ~листинга~«\l__bbt_code_key_str»~неизвестен~и~пропущен }
              }
          }
          {
            \tl_if_blank:nF {##1}
              { \str_set:Ne \l__bbt_code_language_str { \tl_trim_spaces:n {##1} } }
          }
      }
    \exp_args:NV \__bbt_code_language:nn \l__bbt_code_language_str {#2}
    \str_if_empty:NF \l__bbt_code_lines_str { \__bbt_code_lines: }
  }
\cs_generate_variant:Nn \seq_set_split:Nnn { Nne }
\cs_generate_variant:Nn \str_lowercase:n { e }
\cs_generate_variant:Nn \tl_trim_spaces:n { e }
\cs_generate_variant:Nn \str_case:nnF { V }

% lines=10-25 → firstline и lastline в \l__bbt_code_range_tl. Тире «–» и «—» — то же,
% что «-», пробелы не важны. Непонятное значение — весь файл и предупреждение в логе.
% Ключи идут в необязательный аргумент \lstinputlisting: \lstset не годится, listings
% сбрасывает их перед каждым листингом.
\tl_new:N \l__bbt_code_range_tl
\cs_new_protected:Npn \__bbt_code_lines:
  {
    \regex_replace_all:nnN { [\s\{\}] } { } \l__bbt_code_lines_str
    \regex_replace_all:nnN { [\x{2013}\x{2014}] } { - } \l__bbt_code_lines_str
    \regex_extract_once:nVNTF { \A ([1-9]\d*) (?: - ([1-9]\d*) )? \Z }
      \l__bbt_code_lines_str \l__bbt_code_match_seq
      {
        \tl_set:Ne \l_tmpa_tl { \seq_item:Nn \l__bbt_code_match_seq { 2 } }
        \tl_set:Ne \l_tmpb_tl { \seq_item:Nn \l__bbt_code_match_seq { 3 } }
        \tl_if_empty:NT \l_tmpb_tl { \tl_set_eq:NN \l_tmpb_tl \l_tmpa_tl }
        \int_compare:nNnTF { \l_tmpa_tl } > { \l_tmpb_tl }
          {
            \ClassWarning { mtuci-report }
              { Строки~листинга~«\l__bbt_code_lines_str»~идут~наоборот:~показан~весь~файл }
          }
          {
            \tl_set:Ne \l__bbt_code_range_tl
              { firstline = \l_tmpa_tl, lastline = \l_tmpb_tl }
          }
      }
      {
        \ClassWarning { mtuci-report }
          { Строки~листинга~«\l__bbt_code_lines_str»~непонятны:~показан~весь~файл }
      }
  }
\cs_generate_variant:Nn \regex_extract_once:nnNTF { nV }

% \bbtCodeFile[язык, lines=10-25]{путь}{подпись}{метка} — листинг из файла: весь файл
% или строки с 10-й по 25-ю.
\NewDocumentCommand \bbtCodeFile { O{} m m m }
  {
    \group_begin:
      \tl_clear:N \l__bbt_code_range_tl
      \__bbt_code_options:nn {#1} {#2}
      \__bbt_code_input:Vnnn \l__bbt_code_range_tl {#2} {#3} {#4}
    \group_end:
  }
\cs_new_protected:Npn \__bbt_code_input:nnnn #1 #2 #3 #4
  { \lstinputlisting [ #1, caption = {#3}, label = {#4} ] {#2} }
\cs_generate_variant:Nn \__bbt_code_input:nnnn { V }

% Окружение bbtcode{язык}{подпись}{метка} — листинг текстом. Код — со следующей строки.
\lstnewenvironment { bbtcode } [3]
  {
    \__bbt_code_language:nn {#1} { }
    \lstset { caption = {#2}, label = {#3} }
  }
  { }
\ExplSyntaxOff

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
