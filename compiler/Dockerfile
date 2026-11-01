# Образ сервиса компиляции LaTeX (architecture.md, раздел 6).
# Год TeX Live — в теге. Отпечаток закрепляет конкретную сборку: без него тег могут
# пересобрать, и результат сборок поменяется незаметно.
FROM texlive/texlive:TL2025-historic@sha256:7056390eac37715fd3e01875037ceb4016cb17d44c611f7bbbfa7a012007979f

# Liberation Serif, Sans и Mono совпадают по метрикам с Times New Roman, Arial и Courier New
# и содержат кириллицу. Кэш fontconfig строится здесь: во время работы корень только для чтения.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

# В базовом образе не собран xelatex.fmt (форматы pdflatex и lualatex есть).
# Без него XeLaTeX пытается собрать формат при каждом запуске и не может: корень только для чтения.
RUN fmtutil-sys --byengine xetex > /dev/null

# Сборки идут не от root. Домашняя папка нужна под кэши fontconfig и TeX.
RUN useradd --system --uid 10001 --create-home --home-dir /home/compiler \
        --shell /usr/sbin/nologin compiler \
    && mkdir -p /opt/blablatex/tex

# Общий класс шаблонов (templates/_shared) лежит в /opt/blablatex/tex.
# «//» — искать и во вложенных папках, пустой элемент в конце — стандартные пути TeX Live.
ENV TEXINPUTS=.:/opt/blablatex/tex//: \
    HOME=/home/compiler

USER compiler
WORKDIR /home/compiler
