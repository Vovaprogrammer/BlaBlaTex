# Образ воркера бэкенда для docker compose (architecture.md 2, 13): выполняет задачи из
# очереди — сборки, позже прогоны агента и извлечение текста. API в dev работает на хосте.
# Отпечаток закрепляет конкретную сборку образа: тег могут пересобрать.
FROM python:3.12-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

# Та же uv, что в compiler/Dockerfile и [tool.uv] в pyproject.toml. Python — из образа.
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/blablatex/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Задачи идут не от root. uid 1000 — как у первого пользователя в Linux: файлы, которые
# воркер пишет в общую с API папку хранилища, остаются доступны API на хосте.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin worker

WORKDIR /opt/blablatex/backend
# Сначала только зависимости: этот слой пересобирается, лишь когда меняется uv.lock.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-cache --no-install-project
COPY app ./app

ENV PATH=/opt/blablatex/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER worker
# Один процесс: компилятор всё равно собирает не больше двух проектов сразу (9.7),
# а задачи внутри процесса идут параллельно.
CMD ["taskiq", "worker", "app.worker:broker", "--workers", "1"]
