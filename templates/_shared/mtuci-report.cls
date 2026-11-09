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
\setlength\parindent{1.25cm}
\RequirePackage{indentfirst}
% Без отступов между абзацами.
\setlength\parskip{\z@}
% Выравнивание по ширине без вылезающих за поле строк: если строку не разбить
% красиво, TeX лучше чуть растянет пробелы, чем залезет в правое поле.
\setlength\emergencystretch{2em}
% Страница не растягивается по высоте ради ровного низа: отбивки остаются точными.
\raggedbottom

% ---------------------------------------------------------------------------
% 3. Нумерация страниц: арабские цифры внизу по центру, без точки.
% ---------------------------------------------------------------------------
\pagestyle{plain}

\endinput
