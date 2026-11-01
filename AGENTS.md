# BlaBlaTex — правила для ИИ-агентов и людей

BlaBlaTex — веб-сервис для студентов: загружаешь методичку, код и скриншоты, получаешь отчёт по шаблону дисциплины в PDF (LaTeX под капотом). Потом — ВКР, статьи, презентации. Второе русло — MCP-сервер для Claude Code.

- Архитектура и контракты: `docs/architecture.md` — источник правды.
- Задачи: `docs/tasks/` (README — процесс; backend, frontend, ai-mcp, templates — задачи по зонам).

## Как работать над задачей

Коммиты и PR делаешь ты сам, без отдельного разрешения на каждый шаг. Мёржит только человек.

1. Тебе дают ID задачи (например, `B1.3`). Найди её в `docs/tasks/*.md` и прочитай разделы `docs/architecture.md`, указанные в поле «Контекст».
2. **План.** В режиме планирования покажи человеку, какие файлы затронешь и что войдёт в каждый коммит из списка задачи. Код не пиши, пока план не одобрен.
3. **Ветка.** `git switch develop && git pull && git switch -c <ветка из задачи>`.
4. **Коммиты** — строго по списку задачи, по одному:
   - код вместе с тестами;
   - линтер и тесты зоны;
   - `git add` и `git commit` только при зелёном результате;
   - короткий отчёт человеку после каждого коммита.
5. **Рамки.** Не выходи за рамки задачи. Заметил проблему рядом — допиши её в описание PR, молча не чини.
6. **Контракты** (`docs/architecture.md`, раздел 9) сам не меняй. Если без изменения не обойтись — остановись и спроси. Изменение контракта — отдельный коммит, который обновляет и `architecture.md`, и `backend/openapi.json`.
7. **Документация.** Не уверен в API библиотеки — смотри документацию установленной версии, а не память. Особенно PydanticAI, MCP SDK, Taskiq, Tailwind v4, shadcn/ui, react-pdf.
8. **Самопроверка.** Запусти `/code-review develop...HEAD`. Находки исправь коммитом `fix: address review findings` или объясни в PR.
9. **PR.**
   - `git push -u origin <ветка>`;
   - `gh pr create --base develop --title "<ID>: <название задачи>" --body-file <файл>`, тело — по `.github/pull_request_template.md`;
   - пришли человеку ссылку на PR.
10. **Замечания ревьюера** исправляй новыми коммитами в той же ветке и пушь.

## Авторство: только человек

Автор коммитов и PR — человек, который запустил агента. Claude не должен попадать в contributors репозитория. Поэтому:
- Не добавляй в коммиты строки `Co-Authored-By`, `Claude-Session` и ссылки на сессии.
- Не добавляй в описание PR «Generated with Claude Code».
- Не меняй `git config`, не передавай `--author`, не используй `--no-verify`.
- Атрибуцию отключает `.claude/settings.json`, строки вырезает хук `.githooks/commit-msg`, а CI-проверка `no-ai-attribution` не пропустит PR со следами авторства ИИ.

## Git

- Ветка от `develop`: `<type>/<id>-<коротко>`, например `feat/b1.3-files-api`.
- Коммиты — Conventional Commits на английском, не длиннее 72 символов: `feat(projects): add file tree endpoint`. Типы: feat, fix, refactor, test, docs, chore, ci.
- Один коммит — одно логическое изменение, после него проект собирается и тесты проходят.
- Запрещено:
  - пушить в `develop` и `main`;
  - force push;
  - мёржить PR (`gh pr merge`) — это делает человек после зелёного CI, через «Rebase and merge».
- Никогда не коммить: `.env`, ключи, токены, персональные данные, реальные методички и отчёты студентов, большие бинарники.

## Команды

```
# инфраструктура
docker compose up -d                      # postgres, redis, compiler (+ worker)
docker compose run --rm compiler check-template templates/<slug>

# backend
cd backend
uv sync
uv run alembic upgrade head
uv run fastapi dev app/main.py            # API на :8000
uv run taskiq worker app.worker:broker    # воркер (с этапа 2)
uv run ruff check . && uv run ruff format --check .
uv run pytest
uv run pytest -m compiler                 # сборки с настоящим компилятором, нужен docker compose up -d
uv run python -m app.scripts.export_openapi   # обновить backend/openapi.json

# compiler
cd compiler
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest                             # все тесты, нужен Docker: собирают образ и гоняют его
uv run pytest -m "not container"          # быстрые, без Docker

# frontend
cd frontend
pnpm install
pnpm dev                                  # :5173, /api проксируется на :8000
pnpm gen:api                              # типы из ../backend/openapi.json
pnpm lint && pnpm typecheck && pnpm test
pnpm test:e2e                             # Playwright (с этапа 3)
```

Если команды ещё нет, её добавляет задача этапа 0–1 своей зоны. Не придумывай другие.

## Бэкенд (Python)

- Python 3.12, async везде. HTTP-запросы — только через `httpx.AsyncClient`, `requests` запрещён. Не блокируй event loop: тяжёлое и долгое — в воркер.
- Модуль `app/modules/<name>/`:
  - `router.py` — только HTTP;
  - `service.py` — логика, без импорта FastAPI;
  - `models.py` — SQLAlchemy;
  - `schemas.py` — Pydantic.
- В чужие таблицы — только через сервис модуля-владельца.
- Доступ к проекту — через зависимость, которая проверяет владельца. Чужой проект → 404.
- Ошибки: `raise AppError(code, message, status)`, формат — `architecture.md` 9.2. `message` — на русском.
- Конфиг — только через `app/core/config.py` (pydantic-settings), `os.getenv` в модулях запрещён.
- Логи — structlog. Без `print`. Никогда не логировать пароли, токены, ключи и содержимое файлов пользователей.
- Миграция Alembic лежит в том же коммите, что и модель. Смёрженные миграции не редактируются — только новая миграция.
- Тесты:
  - pytest с реальным Postgres из compose/CI, каждый тест в транзакции с откатом;
  - LLM в тестах — только тестовая модель PydanticAI или `FakeProjectTools`, сетевые вызовы к провайдерам запрещены.
- Типы: аннотации везде; `Any` — только с комментарием, почему.
- Комментарии и docstring — на русском, идентификаторы — на английском.

## Фронтенд (TypeScript)

- TS strict, без `any`.
- Данные с сервера — только через TanStack Query и сгенерированный клиент из `src/api/`. Типы API руками не писать.
- Код фичи — в `src/features/<feature>/`, общее — в `src/components/`, shadcn — в `src/components/ui/` (без нужды не править).
- Тексты интерфейса — на русском, простые. Пользователь не обязан знать LaTeX.
- Без `console.log` в коммитах. Ошибки показывать тостом или компонентом ошибки, с `message` из ответа сервера.
- `localStorage` — только для удобств (размеры панелей, последняя вкладка), всегда в try/catch. Токены и данные в нём не хранить.
- Тесты: vitest + Testing Library; моки API — MSW.

## Шаблоны LaTeX

- Движок — XeLaTeX. Без shell-escape, поэтому без `minted` (используй `listings`). Без `inputenc` и `fontenc[T2A]`.
- Общий класс `templates/_shared/mtuci-report.cls`: макросы только добавлять, существующие не переименовывать и не менять их поведение.
- Данные студента и проекта — только через макросы `\bbt...` из `meta.tex` (`architecture.md` 9.6). Никакого хардкода ФИО и групп.
- Каждый шаблон должен собираться: `docker compose run --rm compiler check-template templates/<slug>`.

## Безопасность — всегда

- Компилятор не получает секретов и доступа в интернет. Флаги: `-no-shell-escape`, `-norc`, `openin_any=p`. Файлы `latexmkrc` запрещены.
- Все пути файлов проекта проходят валидацию (`architecture.md` 9.8).
- Ключи LLM пользователей хранятся только зашифрованными; наружу отдаются последние 4 символа.
- ИИ не выдумывает результаты, числа, вывод программ и источники — только из материалов и инструментов.
