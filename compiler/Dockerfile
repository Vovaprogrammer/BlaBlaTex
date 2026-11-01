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

# Python 3.12 для HTTP-сервиса ставит uv: в базовом образе Python другой версии.
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/opt/blablatex/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /opt/blablatex/compiler
# Сначала только зависимости: этот слой пересобирается, лишь когда меняется uv.lock.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-cache --no-install-project
# Сам сервис ставится пакетом: так появляется команда check-template, а app
# импортируется из любой рабочей папки.
COPY app ./app
RUN uv sync --locked --no-dev --no-cache --no-editable

# Общий класс шаблонов (templates/_shared) лежит в /opt/blablatex/tex.
# «//» — искать и во вложенных папках, пустой элемент в конце — стандартные пути TeX Live.
# openin_any/openout_any=p: TeX не читает и не пишет по абсолютным путям и через «..»,
# только в рабочей папке и в своих системных деревьях. shell_escape=f — \write18 выключен
# даже в ограниченном режиме, вдобавок к -no-shell-escape.
ENV TEXINPUTS=.:/opt/blablatex/tex//: \
    openin_any=p \
    openout_any=p \
    shell_escape=f \
    HOME=/home/compiler \
    PATH=/opt/blablatex/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER compiler
# Отсюда check-template видит шаблоны по путям templates/<slug>: compose монтирует их в /srv/templates.
WORKDIR /srv
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
