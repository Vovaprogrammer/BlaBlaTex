# Бэкенд и инфраструктура — задачи

**Зона:** `backend/app/core`, модули `auth`, `profiles`, `projects`, `materials` (хранение), `builds`, `chat`, `review`; `compiler/`; `docker-compose*.yml`, `Caddyfile`, `.github/workflows/`.
**Перед любой задачей** агент читает `AGENTS.md`, `docs/architecture.md` (разделы из «Контекста») и `docs/tasks/README.md`.

---

## Этап 0 — подготовка

### B0.1 Новый скелет репозитория
**Ветка:** `chore/b0.1-skeleton` · **Зависит от:** — · **Контекст:** 3, 13

Перед началом человек:
1. ставит тег `legacy-v0` на текущий `main` и пушит его;
2. создаёт `develop` от `main`.

**Коммиты:**
1. `chore: remove legacy code (kept in tag legacy-v0)` — удалить старые `backend/`, `frontend/`, `docker-compose.yml`. README — коротко: что за проект, где документация, раздел «Подготовка рабочего места» из `docs/tasks/README.md`.
2. `docs: add agent rules, architecture and task files` — весь пакет документации:
   - `AGENTS.md`, `CLAUDE.md`;
   - `.claude/settings.json`, `.githooks/commit-msg`, `.gitattributes`;
   - `.github/pull_request_template.md`, `.github/workflows/no-ai-attribution.yml`;
   - `docs/`.

   Перед коммитом выполнить `git add .githooks/commit-msg && git update-index --chmod=+x .githooks/commit-msg`, чтобы хук был исполняемым у всех. После коммита — `git config core.hooksPath .githooks`.
3. `chore(backend): uv project with FastAPI app factory and health endpoint` — `backend/pyproject.toml`, `app/main.py` с `create_app()`, `app/core/config.py` (pydantic-settings), `app/core/logging.py` (structlog), `GET /api/v1/health` → `{"status": "ok"}`.
4. `chore(backend): ruff and pytest setup with first test` — правила ruff (включая isort, pyupgrade, bugbear), pytest-asyncio, тест health через `httpx.AsyncClient`.
5. `chore: docker-compose for dev infrastructure` — postgres 17 и redis 7 с healthcheck и volume; `.env.example` со всеми переменными без значений.

**Готово, когда:** на чистой машине (в том числе Windows + Docker Desktop) по README поднимается инфраструктура и проходит `uv run pytest`.
**Не делать:** не переносить старый код «на всякий случай» — он в теге.

### B0.2 CI и правила репозитория
**Ветка:** `ci/b0.2-backend-ci` · **Зависит от:** B0.1

**Коммиты:**
1. `ci(backend): ruff and pytest workflow with postgres service` — запуск на PR в `develop` и `main`, кэш uv.
2. `chore: CODEOWNERS for review routing` — зоны из `docs/tasks/README.md`, GitHub-логины команды. Позже файл удалён: ревью по желанию.

**Вручную, не коммитом:**
- защитить `main` и `develop`: PR обязателен, approve не нужен, запрет force-push;
- сделать обязательными проверки CI, включая `no-ai-attribution`;
- оставить только «Rebase and merge»;
- включить автоудаление веток после merge.

**Готово, когда:**
- PR с ошибкой линтера краснеет и не мёржится;
- PR с коммитом, где есть `Co-Authored-By: Claude`, тоже краснеет.

### B0.3 ADR: архитектура и хостинг
**Ветка:** `docs/b0.3-adr` · **Зависит от:** B0.1

**Коммиты:**
1. `docs(adr): 0001 modular monolith and tech stack` — коротко: контекст, решение, последствия. Основа — `architecture.md`.
2. `docs(adr): 0003 hosting target` — где разворачиваемся: VPS в РФ, сервер университета или за рубежом. Решение связано с выбором LLM-провайдера в ADR 0002 (A0.1).

---

## Этап 1 — скелет

### B1.0 Контракт API этапа 1 (заглушки) — делается первой
**Ветка:** `feat/b1.0-api-contract` · **Зависит от:** B0.1 · **Контекст:** 9.1, 9.2

Блокирует весь фронт этапа 1.

**Коммиты:**
1. `feat(api): AppError and unified error responses` — `app/core/errors.py`. Обработчики для `AppError`, ошибок валидации и непойманных исключений — всё в формате 9.2.
2. `feat(api): schemas and stub routes for sprint 1 endpoints` — Pydantic-схемы и роуты auth, profile, templates, projects, tree/files, builds. Все отвечают `501`, но схемы запросов и ответов полные.
3. `chore(api): export openapi.json snapshot and CI freshness check` — `app/scripts/export_openapi.py` пишет `backend/openapi.json`; CI падает, если файл устарел.

**Готово, когда:** `openapi.json` в репозитории, `/api/docs` показывает все эндпоинты этапа 1, фронт генерирует из него типы.
**Не делать:** логику — только схемы.

### B1.1 Слой базы данных
**Ветка:** `feat/b1.1-db` · **Зависит от:** B0.1 · **Контекст:** 4, 5

**Коммиты:**
1. `feat(db): async engine, session dependency and settings` — `app/core/db.py`, пул, `get_session`.
2. `feat(db): declarative base with uuid pk, timestamps and alembic` — `Base`, миксины `id`/`created_at`/`updated_at`; Alembic async и автогенерация; соглашение об именах ограничений.
3. `test(db): postgres fixtures with per-test transaction rollback` — отдельная тестовая БД, миграции применяются один раз за сессию тестов.

**Готово, когда:** `alembic upgrade head` проходит на пустой БД; фикстуры работают в CI.

### B1.2 Авторизация и профиль
**Ветка:** `feat/b1.2-auth` · **Зависит от:** B1.0, B1.1 · **Контекст:** 5, 9.1, 9.2

**Коммиты:**
1. `feat(auth): user and session models with migration` — `users`, `sessions` по схеме из раздела 5.
2. `feat(auth): password hashing and session service` — `pwdlib[argon2]`. Токен сессии — 32 случайных байта, в БД хранится sha256. Срок — 30 дней со скользящим продлением.
3. `feat(auth): register, login, logout and me endpoints` — cookie `bbt_session`. При регистрации обязательно `consent: true`, сохраняется `consent_at`. Email приводится к нижнему регистру, пароль — от 8 символов.
4. `feat(auth): CSRF guard for cookie-authenticated unsafe requests` — без `X-CSRF-Protection: 1` → 403.
5. `feat(profile): profile model, migration and GET/PUT /profile` — профиль создаётся пустым при регистрации.

**Готово, когда:** есть тесты на неверный пароль, повторный email (в разном регистре), истёкшую сессию, logout, отсутствие CSRF-заголовка и чтение чужого профиля.
**Не делать:** Supabase, JWT в `localStorage`, `python-jose`, `passlib`.

### B1.3 Проекты и текстовые файлы
**Ветка:** `feat/b1.3-files-api` · **Зависит от:** B1.2 · **Контекст:** 5, 9.1, 9.2, 9.8

**Коммиты:**
1. `feat(projects): project model, migration and CRUD` — зависимость `get_owned_project`: чужой или несуществующий проект → 404.
2. `feat(projects): file model and path validation` — `files` по схеме из раздела 5; `validate_path()` по 9.8 с таблицей тестов на допустимые и запрещённые пути.
3. `feat(projects): tree and text file read/write with optimistic locking` — `GET /tree`, `GET/PUT /files/{path}`. `ETag`/`If-Match` → 412 `file_conflict` с `current_version`; `If-None-Match: *` → 409, если файл уже есть. Промежуточные папки создаются автоматически.
4. `feat(projects): folders, move/rename and delete` — перемещение папки обновляет пути вложенных файлов в одной транзакции; удаление папки рекурсивное.

**Готово, когда:** тесты покрывают пути (`..`, абсолютные, обратные слеши, `latexmkrc`, скрытые), конфликт версий, переименование папки с вложенными, доступ к чужому проекту.
**Не делать:** ревизии (B2.5), бинарные файлы (B2.2).

### B1.4 Сервис компиляции
**Ветка:** `feat/b1.4-compiler` · **Зависит от:** B0.1 · **Контекст:** 6, 9.7

**Коммиты:**
1. `feat(compiler): docker image with pinned TeX Live and Liberation fonts` — `compiler/Dockerfile` на основе `texlive/texlive` с годом в теге, `fonts-liberation2`, пользователь без root, `TEXINPUTS=.:/opt/blablatex/tex//:`.
2. `feat(compiler): POST /compile — tar in, tar out` — маленький сервис (FastAPI или Starlette): распаковать во временную папку, `latexmk -norc ... -no-shell-escape`, упаковать `result.json`, `output.pdf`, `output.log`, `output.synctex.gz`. Таймаут — убивать всю группу процессов.
3. `feat(compiler): sandbox settings in image and compose` — `openin_any=p`, `openout_any=p`; сервис только во внутренней сети; `mem_limit`, `cpus`, `pids_limit`, `read_only` + tmpfs; в окружении нет секретов; `templates/_shared` монтируется в `/opt/blablatex/tex` в dev.
4. `test(compiler): security tests` — каждая атака должна провалиться:
   - `\input{/etc/passwd}` и `\input{../x}`;
   - `\write18` / `\immediate\write18`;
   - файл `.latexmkrc` с Perl-кодом;
   - бесконечный цикл (должен сработать таймаут);
   - чтение `/proc/self/environ`;
   - сетевой запрос.
5. `feat(compiler): check-template entrypoint for templates CI` — `check-template templates/<slug>`: копирует шаблон во временную папку, кладёт `templates/<slug>/meta.sample.tex` как `meta.tex`, собирает и выводит ошибки.

**Готово, когда:** документ с кириллицей, Liberation Serif и `listings` собирается; все тесты атак проходят; T1.4 может использовать `check-template`.
**Не делать:** логику проектов в компиляторе — он ничего не знает о БД.

### B1.5 Сборки
**Ветка:** `feat/b1.5-builds` · **Зависит от:** B1.3, B1.4 · **Контекст:** 5, 6, 9.1, 9.7

**Коммиты:**
1. `feat(core): Storage interface with local disk implementation` — `put(bytes) → sha256`, `get`, `exists`, `delete`, `open_stream`; раскладка по папкам `ab/cd/<sha256>`.
2. `feat(builds): build model and compiler client` — `builds` по схеме из раздела 5; `httpx.AsyncClient` к компилятору с таймаутом.
3. `feat(builds): materialize project and run build` — tar из файлов по правилам раздела 6, вызов компилятора, сохранение артефактов в `Storage`, запись `inputs_hash` и кэш: при совпадении хеша отдаётся прошлая успешная сборка.
4. `feat(builds): LaTeX log parser to structured errors` — формат `-file-line-error`, `! LaTeX Error`, «File `x.sty' not found», `Undefined control sequence`; контекст ±10 строк из исходника. Тесты на 8–10 фикстурах логов.
5. `feat(builds): build endpoints` — `POST /projects/{pid}/builds` (на этапе 1 синхронно), `GET /builds/{bid}`, `/pdf`, `/log`, `GET /projects/{pid}/builds/latest`.

**Готово, когда:** проект собирается в PDF, PDF отдаётся ссылкой с `Content-Type: application/pdf`; ошибки содержат файл и строку; повторная сборка без изменений приходит из кэша.
**Не делать:** очередь (B2.3), base64.

### B1.6 Укрепление этапа 1
**Ветка:** `fix/b1.6-hardening` · **Зависит от:** B1.5 · **Контекст:** 6, 9.1, 9.2, 9.8

Исправления по ревью этапа 1 перед этапом 2.

**Коммиты:**
1. `fix(core): keep SQL parameters and locals out of logs` — `hide_parameters` у движка БД; трейсбеки structlog без локальных переменных (бэкенд и компилятор).
2. `fix(api): reject NUL in JSON text fields` — нулевой символ в профиле, названии и полях проекта → 422, а не 500.
3. `fix(projects): roll back after failed file operation` — ошибка после блокировки проекта завершает транзакцию: долгая сессия (агент) не держит блокировку и соединение.
4. `docs(architecture): materials in build and TeX-safe file names` — в сборку идут материалы, кроме документов; в путях запрещены спецсимволы TeX.
5. `fix(projects): forbid TeX special characters in paths`
6. `feat(builds): send materials except documents to the build`
7. `feat(projects): enforce file types and project size from 9.8` — 415 на тип не из 9.8, 413 на проект больше 200 МБ.
8. `fix(projects): early 401 for file write and nosniff on file read`
9. `test(projects): concurrent writes on separate connections` — гонки на настоящих отдельных соединениях.
10. `test: unique test database per pytest run` — параллельные прогоны не мешают друг другу.
11. `ci: pin uv version and update checkout`
12. `ci(compiler): run backend builds against real compiler`

**Готово, когда:** ошибка базы не выводит в лог значения запроса; NUL в JSON → 422; после ошибки операции с файлом сессия не в транзакции; `\bbtCodeFile{materials/lab.py}` собирается; тесты на гонки проходят; два `uv run pytest` одновременно не мешают друг другу.

---

## Этап 2 — ИИ в чате

### B2.1 ProjectTools: интерфейс и фейк — делается первой на этапе 2
**Ветка:** `feat/b2.1-project-tools-contract` · **Зависит от:** B1.3, B1.5 · **Контекст:** 9.4

Блокирует A2.1.

**Коммиты:**
1. `feat(projects): ProjectTools protocol, ToolContext, ToolError and result types` — строго по 9.4.
2. `test(projects): in-memory FakeProjectTools` — фейк для тестов агента: файлы в памяти, `compile()` возвращает заданный сценарий ошибок.

**Готово, когда:** Бирук может писать агента против интерфейса без БД.

### B2.2 Бинарные файлы и материалы
**Ветка:** `feat/b2.2-uploads` · **Зависит от:** B1.5 · **Контекст:** 5, 9.1, 9.8

**Коммиты:**
1. `feat(projects): multipart upload with type and size limits` — `POST /upload`. Текстовые расширения — в `content`, остальное — в `Storage`. MIME определяется по содержимому, а не только по расширению.
2. `feat(projects): download binary files with correct content type` — `GET /files/{path}` отдаёт поток; для SVG — `Content-Security-Policy: sandbox`.
3. `feat(materials): material_text model and extraction status` — при загрузке в `materials/` создаётся запись со статусом `pending`. Само извлечение — задача A2.4.

**Готово, когда:** лимиты 9.8 соблюдаются (тесты на 413 и 415); картинки и код из `materials/` попадают в сборку, документы — нет (раздел 6).

### B2.3 Redis, воркер и асинхронные сборки
**Ветка:** `feat/b2.3-worker` · **Зависит от:** B1.5 · **Контекст:** 2, 4

**Коммиты:**
1. `feat(core): redis client and taskiq broker with worker entrypoint` — `app/worker.py`. Задачи регистрируются в `modules/*/tasks.py`.
2. `feat(builds): run builds in worker` — `POST /builds` → `202` + `build_id`; статусы `queued → running → ok|error|timeout`. Зависшие сборки старше 3 минут помечаются `timeout`.
3. `chore: worker service in docker-compose`

**Готово, когда:** HTTP-запрос сборки возвращается сразу; две сборки одного проекта не идут параллельно — новая отменяет ожидающую.

### B2.4 События и SSE
**Ветка:** `feat/b2.4-events` · **Зависит от:** B2.3 · **Контекст:** 9.3

**Коммиты:**
1. `feat(core): project event bus on Redis Streams` — `publish(project_id, type, data)`, MAXLEN ≈ 1000. Типы событий — enum по 9.3.
2. `feat(core): SSE endpoint with Last-Event-ID replay and keep-alive`
3. `feat(projects,builds): publish file and build events`

**Готово, когда:** две вкладки видят изменения друг друга; после переподключения приходит пропущенное; тест на replay.

### B2.5 Ревизии, changesets, откат и реальная ProjectTools
**Ветка:** `feat/b2.5-changesets` · **Зависит от:** B2.1, B2.4 · **Контекст:** 5, 9.1, 9.4

**Коммиты:**
1. `feat(projects): changesets and file revisions with migration` — каждая запись, перемещение и удаление создают ревизию; всё — через сервис файлов. Версии файлов — сквозные в пределах проекта: файл, созданный заново по старому пути, не начинает снова с 1, и устаревший `If-Match` получает 412 (решение ревью этапа 1; описание `ETag` в 9.1 обновляется отдельным коммитом).
2. `feat(projects): coalesce user autosaves into one changeset` — правки одного пользователя в течение 10 минут без других авторов попадают в один changeset.
3. `feat(projects): changeset diff and revert endpoints` — unified diff по файлам. Откат создаёт новый changeset; если файл менялся после — 409 со списком конфликтующих файлов.
4. `feat(projects): ProjectTools implementation over services` — `read_file` с номерами строк, `edit_file` с проверкой уникальности, `search` через ILIKE по текстовым файлам, `compile` через сервис сборок (ждёт результат, но не дольше таймаута).

**Готово, когда:** тесты одинаково проходят на фейке и на реальной реализации (общий набор контрактных тестов).

### B2.6 Чат и прогоны агента (API)
**Ветка:** `feat/b2.6-chat-api` · **Зависит от:** B2.3, B2.4; функция запуска агента — A2.1 · **Контекст:** 8, 9.1, 9.3

**Коммиты:**
1. `feat(chat): messages and agent_runs models with migration`
2. `feat(chat): post message creates run and enqueues agent job` — `POST /messages` → сообщение пользователя, `agent_runs(queued)`, changeset `author=ai`, задача `run_agent(run_id)`; `GET /messages` с историей.
3. `feat(chat): project lock during run and cancel` — блокировка в Redis с TTL; запись файлов пользователем → 423; `POST /runs/{rid}/cancel` останавливает прогон не позже чем за 5 с; события `project.locked/unlocked`.

**Готово, когда:** второй прогон при активном первом → 423; после падения воркера блокировка снимается по TTL.

---

## Этап 3 — MVP отчётов

### B3.1 Квоты и свой ключ
**Ветка:** `feat/b3.1-quota-byok` · **Зависит от:** A1.1, коммит 3 (`usage`) · **Контекст:** 8, 9.1

**Коммиты:**
1. `feat(llm): encrypted user LLM keys and settings endpoints` — Fernet, ключ шифрования из `APP_ENCRYPTION_KEY`; наружу отдаются только `provider` и `last4`.
2. `feat(llm): daily token quota enforcement and usage endpoint` — проверка перед запуском прогона → 429 `quota_exceeded` с временем сброса; со своим ключом квота не тратится.

### B3.2 Экспорт
**Ветка:** `feat/b3.2-export` · **Зависит от:** B2.2

**Коммиты:**
1. `feat(projects): export sources as zip` — без `materials/`, если не передан `?with_materials=1`.
2. `feat(builds): download PDF with readable filename` — например «ЛР3_Чистяков.pdf», `Content-Disposition` с `filename*` по RFC 5987.

### B3.3 Укрепление безопасности
**Ветка:** `feat/b3.3-hardening` · **Зависит от:** B2.6

**Коммиты:**
1. `feat(core): rate limiting on auth, messages and builds` — счётчики в Redis, ответ 429 `rate_limited`.
2. `feat(core): security headers and production cookie settings`
3. `ci(compiler): run compiler security tests in CI`
4. `feat(auth): delete account with all data` — проекты, файлы, `Storage` (если на blob больше никто не ссылается), сессии.

### B3.4 Продовый деплой
**Ветка:** `chore/b3.4-deploy` · **Зависит от:** все задачи этапов 1–2 · **Контекст:** 13

**Коммиты:**
1. `chore(deploy): production compose and Caddyfile` — фронт отдаётся статикой, `/api` проксируется в API, SSE без буферизации.
2. `chore(deploy): nightly backups for postgres and storage`
3. `docs: deploy and operations guide` — установка, обновление, восстановление из бэкапа, ротация ключей.

**Готово, когда:** стенд доступен по HTTPS, восстановление из бэкапа проверено один раз.

---

## Этап 4 — русло 2

### B4.1 Личные токены
**Ветка:** `feat/b4.1-api-tokens` · **Контекст:** 9.1

**Коммиты:**
1. `feat(auth): personal API tokens — create, list, revoke` — формат `bbt_pat_<32 случайных байта в base62>`; показывается один раз; в БД — sha256; `last_used_at`.
2. `feat(auth): bearer token authentication alongside cookie sessions` — без CSRF для bearer; rate limit на токен.

### B4.2 Публичный API для агентов
**Ветка:** `feat/b4.2-public-api`

**Коммиты:**
1. `refactor(api): consistent list responses and pagination`
2. `docs(api): public API guide for MCP and scripts` — авторизация, типичный сценарий, ошибки.

### B4.3 SyncTeX
**Ветка:** `feat/b4.3-synctex` · **Контекст:** 9.1, 9.7

**Коммиты:**
1. `feat(compiler): synctex query endpoint` — `synctex edit` / `synctex view` по сохранённому `output.synctex.gz`.
2. `feat(builds): synctex edit and view endpoints` — page/x/y ↔ path/line.

### B4.4 Исправления по итогам пилота
Задачи из GitHub Issues с меткой `pilot`. Каждая — отдельный PR.

---

## Этапы 5–7 — ВКР (детализируются позже)

- **B5:**
  - поиск по проекту (`pg_trgm`) и API оглавления;
  - импорт DOCX через Pandoc в воркере (вместе с A5);
  - лимиты для больших проектов.
- **B6:**
  - роль преподавателя, группы и курсы;
  - отправка на проверку = снимок ревизий;
  - статусы;
  - комментарии к строке и к месту в PDF;
  - уведомления в интерфейсе.
- **B7:**
  - diff между отправками: текстовый и `latexdiff` в компиляторе;
  - хранение результатов нормоконтроля по отправке.
