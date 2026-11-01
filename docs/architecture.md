# BlaBlaTex — архитектура

Версия 2 (30.10.2026). Это источник правды для людей и ИИ-агентов. Задачи и порядок работ — в `docs/tasks/`.
Раздел «Контракты» меняется только отдельным коммитом.

## 1. Продукт в двух словах

Студент загружает материалы (методичку, задание, код, скриншоты, пояснения) и получает готовый отчёт по шаблону дисциплины в PDF. LaTeX работает под капотом, но исходник всегда доступен. Позже — ВКР с проверкой у преподавателя, статьи и презентации.

Два русла:
1. **Веб-интерфейс:** дерево файлов, чат с ИИ, PDF. Редактор LaTeX — вкладка, а не центр.
2. **MCP-сервер:** для Claude Code и других агентов. Текст пишет модель пользователя, сервер даёт профиль, шаблоны, сборку и проверки.

Принципы:
- Программа отвечает за факты, ИИ — за текст. Числа, результаты и вывод программ берутся только из материалов, источники — только через инструменты поиска.
- Каждый отчёт компилируется; ошибки сборки исправляются автоматически.
- Шаблон дисциплины задаётся один раз и работает для всех.

## 2. Главная идея: одно ядро, три клиента

Ядро — операции над проектом: файлы, шаблон, профиль, материалы, компиляция, проверки. Ими пользуются:
1. веб-интерфейс — через REST;
2. встроенный ИИ-агент — через интерфейс `ProjectTools` (см. 9.4);
3. MCP-сервер — через тот же REST с личным токеном.

Система — модульный монолит на FastAPI, отдельный сервис компиляции в песочнице и фоновый воркер.

```
 Браузер (React SPA)                    Claude Code / opencode / Cursor
        │ HTTPS, cookie-сессия                    │ stdio
        │                              blablatex-mcp (у пользователя)
        │                                         │ HTTPS, личный токен
        ▼                                         ▼
 ┌──────────────── Caddy: TLS, статика фронта, /api → API ─────────────────┐
                                  │
          API · FastAPI (модульный монолит)
          auth · profiles · projects · materials · templates · builds · chat
          agent · (позже) review, checks
             │             │                 │                  │
        PostgreSQL       Redis          Хранилище файлов     LLM-провайдер
                     (очередь Taskiq,   (диск → S3)          (OpenAI-совместимый
                      Redis Streams                           API)
                      для событий)
                           │
          Worker · Taskiq: прогоны агента, извлечение текста, сборки
                           │ HTTP, только внутренняя сеть
          Compiler · TeX Live + latexmk: без секретов, без интернета, с лимитами
```

## 3. Структура репозитория

```
BlaBlaTex/
  AGENTS.md, CLAUDE.md          правила для агентов
  .claude/settings.json         общие настройки Claude Code: без атрибуции ИИ, разрешения
  .githooks/commit-msg          вырезает строки об авторстве ИИ
  .github/                      шаблон PR, workflows (CI, no-ai-attribution)
  docker-compose.yml            dev: postgres, redis, compiler (+ worker с этапа 2)
  docker-compose.prod.yml, Caddyfile
  backend/
    pyproject.toml, uv.lock, openapi.json (снапшот контракта, генерируется)
    app/
      main.py                   create_app()
      worker.py                 брокер Taskiq
      core/                     config, db, errors, security, storage, events, logging
      modules/<name>/           router.py, service.py, models.py, schemas.py, (tasks.py, tools.py)
      scripts/                  export_openapi и т. п.
    migrations/                 Alembic
    tests/
  compiler/                     Dockerfile + маленький HTTP-сервис
  frontend/
    src/app/                    роутер, провайдеры, layout
    src/api/                    сгенерированные типы + клиент
    src/features/<feature>/     auth, profile, projects, workspace, editor, pdf, chat, materials, settings
    src/components/ui/          shadcn/ui
  templates/
    _shared/                    общий класс mtuci-report.cls и стили
    _schema/                    template.schema.json (генерируется из бэкенда)
    <slug>/                     template.yaml, main.tex, sections/, (figures/)
  mcp/
    blablatex-mcp/              Python-пакет MCP-сервера
    claude-plugin/              плагин Claude Code: манифест, .mcp.json, skills/
  eval/                         прогон агента на наборе комплектов (данные — вне репозитория)
  tools/llm-bench/              бенчмарк провайдеров
  docs/                         architecture.md, tasks/, adr/, requirements/, templates.md, design/
```

## 4. Бэкенд

Стек: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 async + asyncpg, Alembic, httpx, pydantic-settings, structlog, Taskiq + taskiq-redis, PydanticAI, pwdlib[argon2], cryptography (Fernet). Пакеты — uv, линтер и форматтер — ruff, тесты — pytest + pytest-asyncio.

Модули (`app/modules/`):

| Модуль | Что внутри |
|---|---|
| auth | пользователи, сессии, личные токены, согласие на ПД |
| profiles | ФИО, группа, факультет, кафедра, роль |
| projects | проекты, файлы, папки, ревизии, changesets, `ProjectTools` |
| materials | хранение материалов и статус обработки, извлечение текста и описание картинок |
| builds | сборки, вызов компилятора, парсер лога, кэш |
| templates | реестр шаблонов, создание проекта, генерация `meta.tex` |
| chat | сообщения, прогоны агента, блокировка проекта |
| agent | LLM-провайдеры, агент, инструменты, промпты, учёт токенов |
| checks | проверки отчёта (с этапа 3) |
| review | отправки на проверку и комментарии (ВКР) |

Правила слоёв:
- `router.py` — только HTTP: схемы, зависимости, коды ответа.
- `service.py` — логика, ничего не знает про FastAPI.
- Модуль не пишет в чужие таблицы напрямую — только через сервис владельца.
- Тяжёлое и долгое (агент, извлечение текста, сборки с этапа 2) — только в воркере.

## 5. Данные

Решения:
- **Дерево файлов — по путям** (`sections/progress.tex`), а не через `parent_id`. Папки — отдельные строки `kind=folder`. Переименование папки — один UPDATE по префиксу в транзакции.
- **Текст и бинарные файлы хранятся раздельно.** Текстовые файлы лежат в Postgres (`content`). Бинарные — в `Storage` по sha256, в таблице только ссылка.
- **Ревизии и changesets с первого дня.** Любая запись файла создаёт ревизию внутри changeset. Каждый прогон агента — один changeset, его можно откатить. Откат создаёт новый changeset, история не переписывается.
- **Supabase не используется.** Если понадобятся старые данные — разовый скрипт: каждый документ превращается в проект с `main.tex`.

```
users          id, email (unique, lower), password_hash, role (student|teacher|admin),
               consent_at, created_at
sessions       id, user_id, token_hash, expires_at, created_at, last_seen_at
api_tokens     id, user_id, name, token_hash, last_used_at, revoked_at, created_at
profiles       user_id (pk), last_name, first_name, middle_name, group_name, faculty,
               department, updated_at
llm_keys       user_id, provider, encrypted_key, last4, created_at
usage          user_id, day, tokens_in, tokens_out, cost, runs        (unique user_id+day)
projects       id, owner_id, title, kind (lab|vkr|article|slides), template_slug,
               template_version, fields jsonb, main_file, engine (xelatex|pdflatex),
               created_at, updated_at
files          id, project_id, path, kind (text|binary|folder), role (source|material|generated),
               content, blob_sha256, mime, size, version, updated_at   unique(project_id, path)
changesets     id, project_id, author (user|ai|mcp|template|system), author_user_id,
               message, run_id, created_at
file_revisions id, file_id, changeset_id, version, op (create|update|delete|move),
               path, content | blob_sha256, created_at
material_text  file_id (pk), status (pending|ready|failed), text, method, pages, description,
               error, updated_at
builds         id, project_id, status (queued|running|ok|error|timeout),
               engine (xelatex|pdflatex), inputs_hash, pdf_sha256, log_sha256, synctex_sha256,
               errors jsonb, pages, duration_ms, created_at
chat_messages  id, project_id, run_id, role (user|assistant|system), parts jsonb, created_at
agent_runs     id, project_id, user_id, status (queued|running|done|failed|cancelled),
               model, tokens_in, tokens_out, cost, changeset_id, error, created_at, finished_at
-- этап 3: report_plans (project_id, plan jsonb, status)
-- ВКР: submissions (project_id, snapshot jsonb, status), review_comments
```

Хранилище спрятано за интерфейсом `Storage` (`put/get/exists/delete` по sha256). Сначала это `LocalStorage` на volume Docker, потом при необходимости S3-совместимое.

## 6. Компиляция

Контейнер `compiler`:
- **Образ:** `texlive/texlive` с зафиксированным годом TeX Live и шрифтами `fonts-liberation2`. Liberation Serif по метрикам совпадает с Times New Roman и содержит кириллицу. TeX Gyre Termes не подходит: в нём нет кириллицы. PT Astra Serif — по желанию, если его можно легально скачать при сборке образа.
- **Как запускается:** `latexmk -norc -<engine> -interaction=nonstopmode -file-line-error -synctex=1 -no-shell-escape -outdir=out main.tex`. Ключ `-norc` нужен потому, что `latexmkrc` — это Perl-код.
- **Безопасность:**
  - `openin_any=p` и `openout_any=p` в окружении: TeX не читает и не пишет файлы вне рабочей папки;
  - нет секретов в окружении, нет доступа в интернет (только внутренняя сеть compose), процесс не от root;
  - лимиты в compose: `mem_limit`, `cpus`, `pids_limit`, read-only root fs + tmpfs; таймаут на сборку.
- **Общий класс** из `templates/_shared` лежит в образе в `/opt/blablatex/tex` и подключается через `TEXINPUTS=.:/opt/blablatex/tex//:`. В dev эта папка монтируется как volume. Проекты пишут просто `\documentclass{mtuci-report}`.
- **Единый движок:** все шаблоны собираются через XeLaTeX. Код вставляется через `listings`, `minted` запрещён. `inputenc` и `fontenc[T2A]` не используются.
- **LuaLaTeX пока не поддерживается** — компилятор собирает только XeLaTeX и pdfLaTeX, на `engine=lualatex` отвечает 422. В REST API и базе бэкенда движка `lualatex` тоже нет: у проекта и сборки `engine` — `xelatex` или `pdflatex`.
  - Почему: при `openin_any=p` LuaTeX запрещает и Lua-функции `io.open` читать файлы по абсолютным путям. Загрузчик шрифтов `luaotfload` открывает так свои файлы из дерева TeX Live, поэтому падает любой документ, даже пустой.
  - Ослабить до `openin_any=r` нельзя: тогда через `\directlua` читается любой файл контейнера, в том числе проекты параллельных сборок — все сборки идут от одного пользователя.
  - Как вернуть: изолировать каждую сборку (отдельный контейнер или отдельный пользователь на сборку) либо добиться, чтобы `luaotfload` читал только из разрешённых путей. После этого — снова прогнать тесты атак `compiler/tests` для LuaLaTeX и вернуть `lualatex` в `Engine` бэкенда (новая миграция для CHECK в `projects` и `builds`).
- **Что уходит в сборку:** все файлы с `role=source` и `generated`, плюс картинки из `materials/`. PDF и DOCX материалов в сборку не идут.
- **Кэш:** ключ — `inputs_hash` = sha256 от отсортированных (path, sha256 содержимого), движка, главного файла и версии образа компилятора.

## 7. Шаблоны

Шаблон — папка `templates/<slug>/` с `template.yaml` (схема в 9.5), `main.tex` и `sections/*.tex`.
- Значения из профиля и полей проекта подставляются через генерируемый `meta.tex` с макросами `\bbt...`. Файлы шаблона — чистый LaTeX без шаблонизатора.
- Общий класс `mtuci-report.cls` реализует требования к оформлению (`docs/requirements/report-formatting.md`, по умолчанию ГОСТ 7.32-2017). В нём есть высокоуровневые макросы (9.6), чтобы ИИ писал простой LaTeX.
- **Правило совместимости:** макросы класса только добавляются. Переименование или изменение поведения существующего макроса ломает старые проекты, поэтому запрещено.
- CI собирает каждый шаблон на каждом PR и проверяет `template.yaml` по JSON Schema.

## 8. ИИ-слой

**Провайдер.** Один интерфейс поверх OpenAI-совместимого API: смена провайдера — это `base_url`, ключ и модель в `.env`.

Роли моделей:
- `main` — пишет и правит отчёт, нужен надёжный tool calling;
- `fast` — названия и короткие ответы;
- `vision` — описание скриншотов.

Выбор провайдера фиксируется в `docs/adr/0002-llm-provider.md` по итогам бенчмарка (задача A0.1).

**Агент — PydanticAI.** Инструменты агента — обёртки над `ProjectTools`. В тестах используется только тестовая модель PydanticAI, реальный провайдер в тестах запрещён. API PydanticAI проверять по документации установленной версии.

**Сценарий отчёта:**
1. **Материалы.** Текст извлекается через `markitdown` (`docling` — если не справится). Код хранится как есть, скриншоты описывает vision-модель.
2. **План (с этапа 3).** Модель возвращает `ReportPlan`: разделы шаблона и какие материалы куда. Пользователь подтверждает план.
3. **Генерация** по разделам, через `edit_file`/`write_file`.
4. **Сборка.** При ошибке агент видит только её и ±10 строк вокруг. Не больше 4 итераций; одна и та же ошибка дважды подряд — остановка и честное сообщение.
5. **Проверки** (с этапа 3).

**Правила агента** (в промптах и инструментах):
- факты — только из материалов;
- `edit_file` вместо переписывания целого файла;
- в LaTeX — только макросы класса;
- `meta.tex` не трогать.

**Блокировка.** Пока прогон активен, проект заблокирован для правок пользователя: ответ `423 project_locked`, в интерфейсе редактор «только чтение».

**Учёт.** Токены и стоимость пишутся в `agent_runs` и `usage`. Квота — дневной лимит токенов на пользователя; со своим ключом квота не расходуется.

**Промпты** лежат файлами в `backend/app/modules/agent/prompts/`. Каждое изменение промпта сопровождается результатами eval в описании PR.

## 9. Контракты

### 9.1 REST API

- Префикс — `/api/v1`, JSON в snake_case, время — ISO 8601 UTC, id — UUID.
- Снапшот контракта лежит в `backend/openapi.json`. Он генерируется (`uv run python -m app.scripts.export_openapi`), CI падает, если снапшот устарел. Фронт генерирует типы из этого файла.

| Метод и путь | Назначение | Этап |
|---|---|---|
| `POST /auth/register` `{email, password, consent: true}` | регистрация + сессия | 1 |
| `POST /auth/login` `{email, password}` | вход | 1 |
| `POST /auth/logout` | выход | 1 |
| `GET /auth/me` | `{user, profile}` | 1 |
| `GET/PUT /profile` | профиль | 1 |
| `DELETE /account` | удалить аккаунт и все данные | 3 |
| `GET /templates`, `GET /templates/{slug}` | шаблоны и их поля | 1 |
| `GET/POST /projects`, `GET/PATCH/DELETE /projects/{pid}` | проекты; POST с `{title, template_slug, fields}` | 1 |
| `GET /projects/{pid}/tree` | список файлов и папок | 1 |
| `GET /projects/{pid}/files/{path}` | содержимое; заголовок `ETag: "<version>"` | 1 |
| `PUT /projects/{pid}/files/{path}` | записать текст; `If-Match: "<version>"` или `If-None-Match: *` для нового | 1 |
| `DELETE /projects/{pid}/files/{path}` | удалить файл или папку | 1 |
| `POST /projects/{pid}/folders` `{path}` | создать папку | 1 |
| `POST /projects/{pid}/move` `{from, to}` | переместить/переименовать | 1 |
| `POST /projects/{pid}/upload` | multipart: `files[]`, `dir`, `role` | 2 |
| `GET /projects/{pid}/material-text?path=materials/...` | извлечённый текст и описание | 2 |
| `POST /projects/{pid}/builds` | запустить сборку (этап 1 — синхронно; этап 2 — `202` + статус) | 1/2 |
| `GET /projects/{pid}/builds/latest`, `GET /builds/{bid}` | статус, ошибки | 1 |
| `GET /builds/{bid}/pdf`, `GET /builds/{bid}/log` | артефакты | 1 |
| `GET /projects/{pid}/changesets` | история | 2 |
| `GET /changesets/{cid}/diff`, `POST /changesets/{cid}/revert` | diff и откат | 2 |
| `GET /projects/{pid}/events` | SSE-поток (9.3) | 2 |
| `GET/POST /projects/{pid}/messages` | чат; POST `{text}` → `{message, run}` | 2 |
| `POST /runs/{rid}/cancel` | отменить прогон | 2 |
| `POST /projects/{pid}/plan`, `PUT /projects/{pid}/plan`, `POST /projects/{pid}/plan/confirm` | план отчёта | 3 |
| `GET /projects/{pid}/export.zip` | исходники архивом | 3 |
| `GET/PUT/DELETE /settings/llm-key`, `GET /usage` | свой ключ, квота | 3 |
| `GET/POST /tokens`, `DELETE /tokens/{id}` | личные токены для MCP | 4 |
| `GET /builds/{bid}/synctex/edit?page&x&y`, `.../view?path&line` | SyncTeX | 4 |

**Содержимое файлов:** `GET /projects/{pid}/files/{path}` отдаёт файл как есть (текстовый — `text/plain; charset=utf-8`) с заголовком `ETag`. `PUT` принимает текст в теле (`text/plain; charset=utf-8`) и отвечает JSON с описанием файла и новой `version`.

**Авторизация:**
- Браузер работает через cookie `bbt_session` (httpOnly, SameSite=Lax, Secure в проде). Для небезопасных методов с cookie обязателен заголовок `X-CSRF-Protection: 1`.
- MCP и скрипты передают `Authorization: Bearer bbt_pat_...`, для них CSRF-проверки нет.
- Чужой проект отвечает `404` — существование не раскрываем.

### 9.2 Формат ошибок

```json
{"error": {"code": "file_conflict", "message": "Файл изменён в другом месте", "details": {"current_version": 7}}}
```

| code | HTTP |
|---|---|
| validation_error | 422 |
| unauthorized | 401 |
| forbidden | 403 |
| not_found | 404 |
| method_not_allowed | 405 |
| already_exists | 409 |
| file_conflict | 412 |
| payload_too_large | 413 |
| unsupported_file_type | 415 |
| project_locked | 423 |
| quota_exceeded | 429 |
| rate_limited | 429 |
| internal | 500 |
| not_implemented | 501 |

`message` — на русском, для пользователя. Ошибки компиляции — это не HTTP-ошибки, а статус сборки.

`not_implemented` — эндпоинт уже описан в контракте, но ещё не сделан (заглушки этапа 1).

У `validation_error` в `details.errors` — список ошибок по полям:

```json
{"error": {"code": "validation_error", "message": "Проверьте введённые данные",
           "details": {"errors": [{"loc": ["body", "email"], "type": "missing", "message": "Обязательное поле"}]}}}
```

- `loc` — где ошибка: `body`, `query`, `path` или `header`, затем имя поля.
- `type` — тип ошибки Pydantic.
- `message` — на русском.
- Введённое значение в ответ не попадает.

### 9.3 События проекта (SSE)

`GET /api/v1/projects/{pid}/events`:
- События хранятся в Redis Stream проекта (MAXLEN ≈ 1000).
- Каждое событие несёт `id`; клиент переподключается с `Last-Event-ID` и получает пропущенное.
- Раз в 15 с отправляется комментарий `: keep-alive`.

Формат: `event: <type>`, `data: <json>`.

| type | data |
|---|---|
| `file.changed` | `{path, version, changeset_id, author}` |
| `file.deleted` | `{path, changeset_id}` |
| `file.moved` | `{from, to, changeset_id}` |
| `material.ready` | `{path, status}` |
| `build.started` | `{build_id}` |
| `build.finished` | `{build_id, status, pages, errors_count}` |
| `run.started` | `{run_id, message_id}` |
| `run.delta` | `{run_id, message_id, text}` |
| `run.tool_call` | `{run_id, call_id, tool, summary}` |
| `run.tool_result` | `{run_id, call_id, ok, summary}` |
| `run.finished` | `{run_id, status, changeset_id, usage: {tokens_in, tokens_out}}` |
| `project.locked` | `{run_id}` |
| `project.unlocked` | `{run_id}` |

`summary` — короткая строка для карточки в чате, например «Изменён sections/progress.tex (+12 −3)».

### 9.4 ProjectTools (бэкенд ↔ агент; MCP повторяет тот же набор через REST)

Файл `backend/app/modules/projects/tools.py`.

```python
@dataclass(frozen=True)
class ToolContext:
    project_id: UUID
    user_id: UUID
    actor: Literal["user", "ai", "mcp"]
    changeset_id: UUID | None      # все записи попадают в этот changeset

class ToolError(Exception):        # code + message; message отдаётся агенту как результат инструмента
    code: str                      # not_found, edit_not_found, edit_not_unique, invalid_path, project_locked ...
    message: str

class ProjectTools(Protocol):
    async def list_files(self) -> list[FileInfo]                    # path, kind, role, size, version
    async def read_file(self, path: str, start_line: int | None = None,
                        end_line: int | None = None) -> FileText    # text с номерами строк, total_lines
    async def search(self, query: str, max_results: int = 50) -> list[SearchHit]   # path, line, snippet
    async def write_file(self, path: str, content: str) -> FileInfo
    async def edit_file(self, path: str, old: str, new: str) -> EditResult
        # old должен встречаться ровно 1 раз; иначе ToolError(edit_not_found | edit_not_unique, с числом вхождений)
    async def delete_file(self, path: str) -> None
    async def compile(self) -> BuildResult
        # status ok|error|timeout, build_id, pages, errors: list[BuildError], warnings_count
    async def list_materials(self) -> list[MaterialInfo]            # path, mime, size, status, description
    async def read_material(self, path: str, offset: int = 0,
                            limit: int = 20_000) -> MaterialText    # кусок текста по символам + total
    async def get_image(self, path: str) -> ImageData               # bytes, mime
    async def get_template_guide(self) -> TemplateGuide             # sections, guides, ai_rules, fields, macros
    async def get_profile(self) -> ProfileData
    async def run_checks(self) -> list[CheckResult]                 # с этапа 3
```

`BuildError = {file, line, message, context, severity}`. В `context` — до 10 строк до и после места ошибки, с номерами строк.

### 9.5 template.yaml

JSON Schema генерируется из Pydantic-модели `TemplateManifest` в `templates/_schema/template.schema.json`. Справочник для авторов шаблонов — `docs/templates.md`.

```yaml
# yaml-language-server: $schema=../_schema/template.schema.json
slug: mtuci-lab-siaod
version: 1
kind: lab                      # lab | vkr | article | slides
title: "Лабораторная работа — СиАОД"
discipline: "Структуры и алгоритмы обработки данных"
engine: xelatex                # xelatex | pdflatex
main: main.tex
fields:                        # спрашиваются при создании проекта
  - key: lab_number
    label: "Номер работы"
    type: int                  # string | int | text | select
    required: true
  - key: lab_title
    label: "Тема работы"
    type: string
    required: true
  - key: variant
    label: "Вариант"
    type: string
  - key: teacher
    label: "Преподаватель"
    type: string
    default: ""
sections:
  - id: goal
    title: "Цель работы"
    file: sections/goal.tex
    required: true
    guide: "1–2 предложения. Взять из методички, не выдумывать."
  - id: progress
    title: "Ход работы"
    file: sections/progress.tex
    required: true
    guide: "По заданиям. Для каждого: что сделано, код (\\bbtCodeFile), скриншот результата (\\bbtScreenshot), пояснение."
  - id: conclusion
    title: "Выводы"
    file: sections/conclusion.tex
    required: true
    guide: "По цели работы; только то, что подтверждают материалы."
ai_rules: |
  Общие правила для ИИ в этом шаблоне.
checks: []                     # с этапа 3, id проверок из docs/checks.md
```

### 9.6 meta.tex и макросы класса

`meta.tex` генерирует бэкенд: `role=generated`, вручную не редактируется. Он пересоздаётся при изменении профиля или полей проекта. Все значения экранируются: `\ & % $ # _ { } ~ ^`.

| Макрос | Значение |
|---|---|
| `\bbtLastName`, `\bbtFirstName`, `\bbtMiddleName` | части ФИО |
| `\bbtShortName` | «Фамилия И. О.» |
| `\bbtFullName` | полное ФИО |
| `\bbtGroup`, `\bbtFaculty`, `\bbtDepartment` | учебные данные |
| `\bbtDiscipline` | из `template.yaml` |
| `\bbtYear`, `\bbtCity` | год и город (по умолчанию «Москва») |
| `\bbt<Key>` | поле шаблона: `key` в CamelCase, например `lab_number` → `\bbtLabNumber` |

Минимальный набор макросов класса `mtuci-report` (можно только расширять):

| Макрос | Назначение |
|---|---|
| `\bbtTitlePage` | титульный лист из макросов `meta.tex` |
| `\bbtScreenshot[width]{path}{caption}{label}` | рисунок «Рисунок N — caption» |
| `\bbtCodeFile[language]{path}{caption}{label}` | листинг из файла |
| окружение `bbtcode`, аргументы `{language}{caption}{label}` | листинг текстом |
| окружение `bbttable`, аргументы `{caption}{label}`, внутри обычный `tabular` | таблица с подписью «Таблица N — caption» |

### 9.7 Compiler API (бэкенд ↔ compiler, внутренняя сеть)

```
POST http://compiler:8080/compile
  multipart: archive = project.tar.gz, main = main.tex, engine = xelatex|pdflatex, timeout_s ≤ 120
→ 200 application/gzip (tar): result.json {status: ok|error|timeout, exit_code, duration_ms},
                              output.pdf (если есть), output.log, output.synctex.gz (если есть)
GET  http://compiler:8080/health
```

- `main` — относительный путь к `.tex`-файлу из архива; в имени только буквы, цифры, пробел и `_ - . /`. latexmk передаёт имя главного файла через shell, и, например, обратная кавычка в нём выполнила бы команду.
- Папка `out/` в архиве запрещена: туда пишутся результаты сборки, и старые файлы оттуда выдавались бы за новый PDF.
- `engine` — по умолчанию `xelatex`. LuaLaTeX не поддерживается, причина — в разделе 6.
- `timeout_s` — от 1 до 120, по умолчанию 60 (9.8). Одновременно идут не больше 2 сборок, остальные запросы ждут очереди — таймаут клиента должен это учитывать.
- Ошибка LaTeX и таймаут — не HTTP-ошибки: ответ `200`, итог — в `status` из `result.json`. При `timeout` поле `exit_code` равно `null`.
- `output.log` — лог TeX. Если TeX не успел запуститься, там вывод `latexmk`.
- Неверный запрос — ответ в формате 9.2:
  - `validation_error` 422 — архив не tar.gz; в архиве ссылки, абсолютные пути, `..` или папка `out/`; `main` не подходит под правила выше; неизвестный `engine`; `timeout_s` вне 1–120;
  - `payload_too_large` 413 — архив больше 200 МБ, в распакованном виде больше 200 МБ или больше 10 000 файлов.
- В dev бэкенд запущен на хосте и внутреннюю сеть compose не видит. Он ходит через `compiler-proxy`: `http://localhost:${COMPILER_PORT:-8080}`. Прокси слушает только `127.0.0.1`, у самого компилятора доступа в интернет нет.

С этапа 4 добавляется `POST /synctex` для запросов SyncTeX.

### 9.8 Пути и лимиты

- Пути в UTF-8 NFC, разделитель `/`.
- Запрещено: ведущий `/`, сегменты `.`, `..` и пустые, символы `\` и `:`, управляющие и невидимые символы (категории Unicode Cc, Cf, Cs, Zl, Zp), скрытые имена (начинаются с `.`), имена `latexmkrc` в любом регистре.
- Максимальная длина пути — 255 символов, сегмента — 100 символов и не больше 255 байт в UTF-8 (предел имени файла в Linux).
- Материалы лежат в `materials/`, `meta.tex` — в корне проекта.
- Лимиты:
  - текстовый файл — до 2 МБ, загружаемый — до 20 МБ;
  - проект — до 200 МБ;
  - сборка — до 60 с, PDF — до 50 МБ;
  - разрешённые типы: `.tex .bib .sty .cls .txt .md .csv`, код (`.py .java .c .cpp .h .js .ts .sql .go .rs .kt .cs`), `.png .jpg .jpeg .svg .pdf .docx .pptx .xlsx`.

## 10. Фронтенд

- **Основа:** Vite + React 19 + TypeScript strict, pnpm. React Router, TanStack Query, Zustand (только состояние UI).
- **Вёрстка:** Tailwind v4 + shadcn/ui, `react-resizable-panels`, `react-arborist` (дерево).
- **Редактор и PDF:** CodeMirror 6 (`@uiw/react-codemirror`, LaTeX — режим `stex` из `@codemirror/legacy-modes`), `@codemirror/merge` для diff, `react-pdf`.
- **Чат:** `react-markdown` + `remark-math` + `rehype-katex`.
- **API и формы:** типы из `backend/openapi.json` через `openapi-typescript` + `openapi-fetch`. SSE — через `@microsoft/fetch-event-source`. Формы — `react-hook-form` + `zod`.
- **Тесты:** vitest + Testing Library, MSW для моков, Playwright для e2e.

Рабочее окно: слева — дерево с секцией «Материалы», в центре — вкладки «Чат» и открытые файлы, справа — PDF. На узком экране панели превращаются во вкладки. Экраны приложения:
1. вход и регистрация;
2. профиль;
3. проекты;
4. мастер нового проекта;
5. рабочее окно;
6. настройки (ключ ИИ, токены MCP).

## 11. Русло 2: MCP

- **Пакет:** `mcp/blablatex-mcp` — локальный stdio-сервер, запускается через `uvx`. Настраивается переменными `BLABLATEX_URL` и `BLABLATEX_TOKEN`. Это клиент REST API, своей бизнес-логики у него нет.
- **Почему локальный:** он сам читает файлы с диска и сохраняет PDF в папку, так что байты не идут через контекст модели. Вывод каждого инструмента — коротко, до ~5 тыс. токенов.
- **Инструменты:** `get_profile`, `list_templates`, `create_project`, `list_projects`, `upload_materials(paths)`, `get_template_guide`, `list_files`, `read_file`, `edit_file`, `write_file`, `compile`, `download_pdf(out_path)`, позже `run_checks`.
- **Безопасность:** `upload_materials` берёт файлы только внутри текущей рабочей папки и отклоняет скрытые файлы и `.env`.
- **Распространение — плагин Claude Code** (`mcp/claude-plugin`): манифест с `userConfig` (токен с `"sensitive": true`), `.mcp.json`, skill `lab-report`. Для opencode и Cursor — обычный конфиг stdio-сервера.
- **Версии:** версию MCP SDK фиксировать строго (у официального SDK в 2026 вышла 2.x с изменённым API).

## 12. ВКР (этапы 5–7)

В базе с самого начала уже есть многофайловость, ревизии и роли. Дальше добавляется:
- шаблон `mtuci-vkr` с библиографией через `biblatex-gost` + biber;
- импорт DOCX через Pandoc в воркере;
- инструменты агента для большого документа: оглавление с диапазонами строк и поиск;
- источники только через Crossref/OpenAlex по DOI/ISBN;
- отправки на проверку как снимки ревизий, со статусами и комментариями к строке или месту в PDF;
- diff версий: построчный, `latexdiff` и ИИ-сводка;
- нормоконтроль: детерминированные проверки, а рекомендации ИИ — отдельной пометкой.

## 13. Инфраструктура

- **dev:** `docker compose up -d` поднимает postgres 17, redis 7, compiler (и worker с этапа 2). API и фронт запускаются локально с hot reload.
- **CI (GitHub Actions):**
  - backend: ruff, pytest с Postgres, свежесть `openapi.json`;
  - frontend: lint, typecheck, test, build;
  - templates: сборка всех шаблонов и валидация `template.yaml`;
  - compiler: тесты безопасности;
  - `no-ai-attribution`: нет следов авторства ИИ в коммитах и описании PR.
- **Авторство:** коммиты и PR делает агент, но от имени разработчика. Атрибуция ИИ отключена в `.claude/settings.json`, хук `.githooks/commit-msg` вырезает строки, CI-проверка блокирует остальное. Claude не попадает в contributors.
- **prod:** один сервер, `docker-compose.prod.yml` + Caddy (TLS). Секреты лежат только в `.env` на сервере. Ночной `pg_dump` и копия хранилища.

## 14. Чего не повторять (из legacy-v0, тег в git)

- Эндпоинты без авторизации.
- Компиляция в контейнере с ключами и без песочницы.
- Синхронный `requests` внутри `async def`.
- PDF в base64 внутри JSON.
- Шрифт Times New Roman, которого нет в образе.
- Шаблоны, зашитые в компонент.
- Хардкод адреса API.
- Токен в `localStorage`.
- `console.log` с токенами.
- 26 отдельных ИИ-функций вместо одного агента с инструментами.
