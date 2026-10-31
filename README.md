# BlaBlaTex

Веб-сервис для студентов: загружаешь методичку, задание, код и скриншоты — получаешь отчёт по шаблону дисциплины в PDF. LaTeX работает под капотом, но исходник всегда доступен. Позже — ВКР с проверкой у преподавателя, статьи и презентации.

Второе русло — MCP-сервер для Claude Code и других агентов: текст пишет модель пользователя, сервер даёт профиль, шаблоны, сборку и проверки.

> Проект переписывается с нуля. Старая версия сохранена в теге `legacy-v0`.

## Документация

- [`AGENTS.md`](AGENTS.md) — правила работы для людей и ИИ-агентов.
- [`docs/architecture.md`](docs/architecture.md) — архитектура и контракты, источник правды.
- [`docs/tasks/`](docs/tasks/README.md) — процесс разработки и задачи по зонам.

## Подготовка рабочего места

Один раз после клонирования:

1. `git config user.name` и `git config user.email`. Email должен быть привязан к твоему GitHub-аккаунту — коммиты агента идут от твоего имени.
2. `git config core.hooksPath .githooks` — включает хук, который вырезает строки об авторстве ИИ.
3. Установить GitHub CLI и выполнить `gh auth login` — через него агент открывает PR от твоего имени.
4. Запустить Claude Code в корне репозитория и подтвердить доверие к папке. Без этого не применяются разрешения из `.claude/settings.json`. Проверка — `/status`: в «Setting sources» есть «Shared project settings».
5. Не включать в личных настройках атрибуцию обратно. `.claude/settings.local.json` и `~/.claude/settings.json` не должны задавать `attribution`.

## Запуск для разработки

Нужны Docker Desktop (или Docker Engine с compose) и [uv](https://docs.astral.sh/uv/). Python 3.12 uv скачает сам.

1. Создать `.env` из шаблона и задать в нём `POSTGRES_PASSWORD`:
   ```bash
   cp .env.example .env              # PowerShell: Copy-Item .env.example .env
   ```
   Если `.env` уже есть (например, от старой версии), не перезаписывайте его — допишите недостающие переменные из `.env.example`.
2. Поднять Postgres и Redis и дождаться статуса `healthy`:
   ```bash
   docker compose up -d
   docker compose ps
   ```
3. Бэкенд:
   ```bash
   cd backend
   uv sync
   uv run pytest
   uv run fastapi dev app/main.py    # API на http://localhost:8000, документация — /api/docs
   ```

Остальные команды — в [`AGENTS.md`](AGENTS.md#команды).

## Лицензия

MIT — см. [`LICENSE`](LICENSE).
