# Образ бэкенда (architecture.md 2, 13): один на API и воркер, команду задаёт compose.
# По умолчанию — воркер: в dev API работает на хосте, а compose запускает только воркер.
#
# Шаблоны отчётов берутся из второго контекста сборки с именем templates — папки templates/
# в корне репозитория: `docker build --build-context templates=templates backend` (compose
# передаёт его сам, additional_contexts). Без него сборка не найдёт шаблоны.
#
# Отпечаток закрепляет конкретную сборку образа: тег могут пересобрать.
FROM python:3.12-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

# Та же uv, что в compiler/Dockerfile и [tool.uv] в pyproject.toml. Python — из образа.
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/blablatex/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# API и воркер работают не от root. uid 1000 — как у первого пользователя в Linux: файлы,
# которые воркер в dev пишет в общую с API папку хранилища, остаются доступны API на хосте.
# Домашняя папка — под кэши библиотек, которые пишут в ~/.cache.
# Папка хранилища принадлежит этому пользователю: новый том Docker берёт владельца отсюда.
RUN useradd --uid 1000 --create-home --home-dir /home/blablatex --shell /usr/sbin/nologin blablatex \
    && mkdir -p /srv/storage \
    && chown blablatex:blablatex /srv/storage

WORKDIR /opt/blablatex/backend
# Сначала только зависимости: этот слой пересобирается, лишь когда меняется uv.lock.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-cache --no-install-project
# Миграции применяет сервис migrate в compose установки: alembic upgrade head.
COPY migrations ./migrations
COPY app ./app
# Шаблоны: их реестр API и воркер читают при старте. В dev compose монтирует папку поверх.
COPY --from=templates . /opt/blablatex/templates

ENV PATH=/opt/blablatex/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORAGE_DIR=/srv/storage \
    TEMPLATES_DIR=/opt/blablatex/templates

USER blablatex
# Один процесс: компилятор всё равно собирает не больше двух проектов сразу (9.7),
# а задачи внутри процесса идут параллельно.
CMD ["taskiq", "worker", "app.worker:broker", "--workers", "1"]
