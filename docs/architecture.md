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
- **Ревизии и changesets с первого дня.** Любая запись файла попадает в changeset — группу правок одного автора — и сохраняет в ревизии прежний вид файла. Каждый прогон агента — один changeset, его можно откатить. Откат создаёт новый changeset, история не переписывается. Подробности — «История правок» ниже.
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
               last_file_version, last_changeset_id, run_lock_id, run_lock_until,
               created_at, updated_at
files          id, project_id, path, kind (text|binary|folder), role (source|material|generated),
               content, blob_sha256, mime, size, version, updated_at   unique(project_id, path)
changesets     id, project_id, author (user|ai|mcp|template|system), author_user_id,
               message, run_id, reverts_id, created_at, updated_at
file_revisions id, changeset_id, file_id, path, kind, content | blob_sha256, mime, size,
               created_at        -- файл до правки; path и kind = null — файла ещё не было
material_text  file_id (pk), status (pending|ready|failed), text, method, pages, description,
               error, updated_at
builds         id, project_id, status (queued|running|ok|error|timeout),
               engine (xelatex|pdflatex), inputs_hash, pdf_sha256, log_sha256, synctex_sha256,
               errors jsonb, pages, duration_ms, started_at, created_at
chat_messages  id, project_id, run_id, role (user|assistant|system), parts jsonb, seq, created_at
agent_runs     id, project_id, user_id, status (queued|running|done|failed|cancelled),
               model, tokens_in, tokens_out, cost, changeset_id, error, cancel_requested_at,
               created_at, finished_at
-- этап 3: report_plans (project_id, plan jsonb, status)
-- ВКР: submissions (project_id, snapshot jsonb, status), review_comments
```

Хранилище спрятано за интерфейсом `Storage` (`put/get/exists/delete` по sha256). Сначала это `LocalStorage` на volume Docker, потом при необходимости S3-совместимое.

**Сборки.** Статусы — `queued` → `running` → `ok` | `error` | `timeout`; итог пишется один раз:
- у проекта не больше одной сборки `queued` и одной `running` — это держат уникальные индексы, сколько бы воркеров ни работало;
- повторный запрос, пока сборка `queued`, возвращает её же: файлы она читает в момент начала (`running`) и соберёт последние правки;
- закончив сборку, воркер сам начинает следующую `queued` того же проекта;
- `started_at` — когда сборка начата; сборка, которая идёт дольше 3 минут, получает `timeout`.

**Материалы.** У каждого файла `role=material` есть строка `material_text` — итог извлечения текста (B2.7); её таблицей владеет модуль materials:
- файл появился в `materials/` (загрузка, создание, перенос туда) — строка со статусом `pending`;
- содержимое изменилось (повторная загрузка, запись текста) — снова `pending`, а `text`, `method`, `pages`, `description` и `error` стираются: ИИ не прочитает текст старой версии;
- переименование и перенос внутри `materials/` строку сохраняют;
- файл перенесён из `materials/` — строка удаляется, файл удалён — удаляется вместе с ним.

**Извлечение текста** (B2.7) — задача воркера:
- Её ставит в очередь сервис файлов после commit каждой записи, от которой материал стал `pending`: загрузка, запись текста, перенос в `materials/`, откат. Очередь недоступна — запись всё равно проходит. Фоновая проверка воркера раз в 30 с снова ставит в очередь материалы, которые ждут дольше 2 минут: так обработаются и материалы, загруженные до B2.7.
- Что получается из файла:

  | Файл | Итог |
  |---|---|
  | `.pdf` | текст через pdfminer — на нём читает PDF и markitdown, но теряет границы страниц. Перед каждой страницей — строка `<!-- Страница N -->`, `pages` — число страниц. Ни на одной странице нет текста (скан) — `failed` |
  | `.docx .pptx .xlsx` | markdown через markitdown; у `.pptx` перед каждым слайдом — `<!-- Slide number: N -->`, `pages` — число слайдов |
  | текст и код (`.txt .md .csv .tex .bib .sty .cls`, исходники) | как есть |
  | `.png .jpg .jpeg` | `ready` без текста; описание — по настройке, см. ниже |
  | `.svg` | `failed`: ИИ не читает SVG, студенту предлагается PNG или JPG |
- `method` у `ready` — чем получен текст: `pdfminer`, `markitdown`, `text` или `image`; у `pending` и `failed` — null.
- Текст длиннее 500 000 символов обрезается по концу строки, в конце — пометка «[Текст обрезан: …]» с длиной всего текста.
- Документ разбирается в отдельном процессе: без секретов в окружении, до 60 с и 1 ГБ памяти (`failed`, если не уложился). Документ Office, который распаковывается больше чем в 200 МБ или из больше чем 10 000 частей, не разбирается. В `error` — понятная причина для студента на русском, подробности — только в лог; содержимое файлов не логируется.
- Итог пишется, только если строку не меняли с тех пор, как задача взяла её в работу: `updated_at` строки меняется при сбросе в `pending`, взятии в работу и повторной постановке в очередь. Так текст старой версии не затрёт сброс после новой загрузки, а повторное задание — итог первого. После записи — событие `material.ready` (9.3) с путём файла на этот момент.
- Описание картинки — `describe_image` (9.4), если включена настройка `MATERIAL_DESCRIBE_IMAGES` (по умолчанию выключена: каждое описание стоит денег). Сбой или нет ответа за 60 с — описание пустое, статус всё равно `ready`. Расход на описание учитывает B3.1.

**История правок.** Всё, что меняет файлы и папки проекта, идёт через сервис файлов и попадает в changeset:
- **Ревизия** — каким был файл или папка до того, как changeset их изменил: путь, вид, текст или ссылка на blob, MIME и размер; `path = null` — файла не было. На файл в changeset — одна ревизия: следующие записи того же changeset в тот же файл её не добавляют. Если между ними файл изменил другой changeset — у файла новая ревизия. Каким файл стал после changeset — это следующая ревизия файла или сам файл сейчас.
- **Кто пишет и куда:**

  | Откуда запись | `author` | changeset |
  |---|---|---|
  | сайт: запись, загрузка, папки, перенос, удаление | `user` | склеивается |
  | MCP (этап 4) | `mcp` | склеивается |
  | `meta.tex` после правки профиля или полей | `system` | новый в каждом проекте, где он изменился |
  | создание проекта из шаблона | `template` | один на все файлы проекта |
  | агент | `ai` | changeset прогона (`ToolContext.changeset_id`, 9.4) |
  | откат | `user` | новый, `reverts_id` — откатанный changeset |

  `author_user_id` — студент, от чьего имени запись.
- **Склейка автосохранений.** Запись `user` или `mcp` попадает в последний changeset проекта (`projects.last_changeset_id` — changeset последней записи), если у него тот же автор и тот же пользователь, он не откат и начат меньше 10 минут назад. Иначе создаётся новый. Так склейку прерывают запись другого автора (ИИ, `meta.tex`) и откат, а вкладки одного студента пишут в один changeset. Откатить можно не больше 10 минут правок за раз.
- **Версии файлов сквозные** в пределах проекта: каждая запись содержимого берёт следующий номер из `projects.last_file_version`. Файл, созданный заново по старому пути, получает новый номер, а не 1, и устаревший `If-Match` получает 412. Перенос номер не меняет. У проектов, созданных раньше, счётчик начинается с самой большой версии их файлов.
- **Проекты до истории.** У их файлов ревизий нет: история начинается с первой правки, и эта правка сохраняет прежний вид файла — её diff и откат работают.
- **Место.** История не входит в лимит проекта 200 МБ (9.8). Текст копируется в ревизию один раз на changeset; blob'ы не копируются — ревизия ссылается на тот же sha256. Поэтому очистка `Storage` (B3.3) не удаляет blob, на который ссылается файл или ревизия.

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
- **Что уходит в сборку:** проект целиком, как в Overleaf, — все файлы с `role=source` и `generated`: `main.tex`, другие `.tex`, картинки. Из материалов (`role=material`, папка `materials/`) — всё, кроме документов `.pdf .docx .pptx .xlsx`. Код и скриншоты из материалов подключаются в отчёт через `\bbtCodeFile` и `\bbtScreenshot`, а методичку и задание читает только ИИ.
- **Кэш:** ключ — `inputs_hash` = sha256 от отсортированных (path, sha256 содержимого), движка, главного файла и версии компилятора. Версию бэкенд берёт из `GET /health` (9.7) перед каждой сборкой: это `COMPILER_VERSION` из `compiler/Dockerfile` и отпечаток файлов общего класса в `/opt/blablatex/tex`. `COMPILER_VERSION` поднимают при любом изменении образа, от которого может поменяться PDF: базовый образ, шрифты, команда `latexmk`. Отпечаток класса компилятор считает сам при каждом запросе: в dev папка смонтирована и меняется без пересборки образа.

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
1. **Материалы.** Текст документов извлекается через `markitdown`, PDF — через pdfminer, чтобы сохранить границы страниц (раздел 5); `docling` — если они не справятся. Код хранится как есть, скриншоты описывает vision-модель.
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
- Блокировка — в строке проекта: `run_lock_id` (чей прогон) и `run_lock_until` (до какого времени, по часам базы). Срок — 30 с, воркер продлевает его каждые 10 с. Упал воркер — через 30 с проект снова можно править.
- Проверка — в той же транзакции, что запись, под блокировкой строки проекта (`lock_project`, раздел 5). Через неё проходят все записи файлов: сохранение, загрузка, папки, перенос, удаление, откат, инструменты агента, `meta.tex`. Прогон занимает проект тоже под блокировкой строки: сохранение, которое уже идёт, закончится раньше, а начатое позже получит 423.
- Во время прогона нельзя: записывать файлы (`user`, `mcp`), менять поля проекта, удалять проект, отправлять новое сообщение. Можно: менять название, собирать, читать. `meta.tex` после правки профиля пишется (`system`): агент его не трогает. ИИ пишет, только если его changeset — changeset прогона, который держит блокировку; иначе `ToolError project_locked`.

**Прогон.** `queued` → `running` → `done` | `failed` | `cancelled`; итог пишется один раз, у проекта не больше одного прогона `queued` или `running` (уникальный индекс).
- `POST /messages` в одной транзакции создаёт сообщение студента, пустой ответ ассистента, прогон `queued` и changeset `ai` с `run_id`, потом ставит задание воркеру. Очередь недоступна — всё созданное удаляется, ответ `500 internal`.
- Воркер занимает проект и переводит прогон в `running`, затем шлёт `project.locked` и `run.started`. Итог прогона, части ответа и снятие блокировки — одна транзакция, после неё — `run.finished` и `project.unlocked`.
- Прежде чем запустить агента, прогон ждёт, пока материалы проекта разберутся (раздел 5): пока есть материалы `pending`, их статусы проверяются раз в секунду, но не дольше 90 с. Дальше агент работает с тем, что готово, — неразобранный материал `read_material` отдаёт как `material_not_ready`. Так «Сделай отчёт» сразу после загрузки видит текст материалов. Блокировка и отмена во время ожидания работают как во время работы агента; отменённый в ожидании прогон агента не запускает.
- Задание может прийти повторно: законченный прогон и прогон, чья блокировка жива, не трогаются; прогон `running` с истёкшей блокировкой получает `failed` («Прогон прервался»). Агент второй раз не запускается. Такие прогоны раз в 30 с закрывает и фоновая проверка воркера, и сам `POST /messages` перед новым прогоном. Прогон, который минуту ждёт в очереди, отправляется воркеру ещё раз.
- Отмена: прогон в очереди сразу получает `cancelled`. У идущего ставится `cancel_requested_at`; воркер проверяет её раз в секунду и взводит `RunRequest.cancel`. Агент не вернулся за 3 с — воркер прерывает его сам. Итог — `cancelled`, пришедший текст сохраняется.
- Исключение из `run_agent` — `failed` с общим сообщением, подробности только в лог.
- История для агента: последние 20 сообщений до запроса и сам запрос. Берётся только текст ответов, без карточек и ошибок; старое сообщение длиннее 4000 символов сокращается с пометкой. Лимит токенов на прогон — настройка `AGENT_RUN_MAX_TOKENS`.
- Текст ответа — то, что агент прислал через `run.delta`. Не прислал ничего, а `RunResult.text` есть — бэкенд шлёт его одним `run.delta`.
- Части ответа (`parts`) воркер сохраняет раз в секунду и в конце; `seq` сообщения — номер последнего события прогона, которое в них вошло (9.3).

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
| `POST /projects/{pid}/upload` | multipart: `files` (поле на каждый файл), `dir` → `{items: [FileInfo]}` | 2 |
| `GET /projects/{pid}/material-text?path=materials/...&offset&limit` | извлечённый текст и описание → `MaterialTextOut` | 2 |
| `POST /projects/{pid}/builds` | поставить сборку в очередь → `202` + `BuildOut` (этап 1 — синхронно) | 1/2 |
| `GET /projects/{pid}/builds/latest?status=ok`, `GET /builds/{bid}` | статус, ошибки; `status=ok` — последняя успешная | 1 |
| `GET /builds/{bid}/pdf`, `GET /builds/{bid}/log` | артефакты | 1 |
| `GET /projects/{pid}/changesets?before&limit` | история правок → `{items: [Changeset], has_more}` | 2 |
| `GET /changesets/{cid}/diff` | что изменил changeset → `{changeset, files: [FileDiff]}` | 2 |
| `POST /changesets/{cid}/revert` | откат → `201` + `Changeset` отката | 2 |
| `GET /projects/{pid}/events` | SSE-поток (9.3) | 2 |
| `GET /projects/{pid}/messages?before&limit` | чат → `{items: [ChatMessage], has_more, active_run}` | 2 |
| `POST /projects/{pid}/messages` `{text}` | сообщение и прогон агента → `201 {message, run}` | 2 |
| `POST /runs/{rid}/cancel` | отменить прогон → `Run` | 2 |
| `POST /projects/{pid}/plan`, `PUT /projects/{pid}/plan`, `POST /projects/{pid}/plan/confirm` | план отчёта | 3 |
| `GET /projects/{pid}/export.zip` | исходники архивом | 3 |
| `GET/PUT/DELETE /settings/llm-key`, `GET /usage` | свой ключ, квота | 3 |
| `GET/POST /tokens`, `DELETE /tokens/{id}` | личные токены для MCP | 4 |
| `GET /builds/{bid}/synctex/edit?page&x&y`, `.../view?path&line` | SyncTeX | 4 |

**Содержимое файлов:** `GET /projects/{pid}/files/{path}` отдаёт файл как есть, с заголовками `ETag`, `X-Content-Type-Options: nosniff` и `Content-Disposition: inline` с именем файла (`filename*` в UTF-8 — для русских имён). Текстовый — `text/plain; charset=utf-8`, бинарный — потоком, с типом, определённым при загрузке; у SVG ещё `Content-Security-Policy: sandbox`: скрипт внутри картинки не выполнится. `PUT` принимает текст в теле (`text/plain; charset=utf-8`) и отвечает JSON с описанием файла и новой `version`; путь бинарного типа (картинки, документы) — `415`.

**Версия в `ETag` и `If-Match`** — сквозной номер записи в проекте (раздел 5), а не счётчик правок одного файла. У файла, созданного заново на месте удалённого, номер новый, поэтому вкладка с `If-Match` удалённого файла получит `412`, а не перезапишет чужой файл. Перенос версию не меняет.

**Загрузка файлов** (`POST /projects/{pid}/upload`):
- Тело — `multipart/form-data`: поле `files` повторяется для каждого файла, `dir` — папка назначения (пусто или нет поля — корень проекта). Путь файла — `dir/имя`; в имени можно передать подпапки через `/`. Путь проверяется по 9.8 после приведения к NFC, недостающие папки создаются сами.
- Роль задаёт путь: в `materials/` — `material`, иначе — `source`.
- Всё или ничего: если не подошёл хотя бы один файл, не сохраняется ни один. Ошибка называет файл в `message`, его путь — в `details.path`. Один путь дважды в запросе — `422`.
- Файл по этому пути уже есть — заменяется, `version` растёт. Файл `role=generated` (`meta.tex`) — `403`; на этом месте папка или над файлом не папка, а файл — `409`.
- Тип — по расширению из 9.8 и по содержимому; не совпало — `415`. `Content-Type` частей не учитывается. Текстовые типы сохраняются в UTF-8 с переводами строк `\n`: UTF-8 с BOM, UTF-16 с BOM и cp1251 перекодируются; двоичное содержимое под текстовым расширением — `415`.
- Порядок проверок, первая ошибка — ответ: имя (`422`) → расширение (`415`) → размер файла (`413`) → содержимое (`415`) → занятые пути (`403`, `409`) → размер проекта (`413`).
- Ответ — `200 {items: [FileInfo]}`, файлы в порядке запроса.

**Текст материалов** (`GET /projects/{pid}/material-text`) — что ИИ видит в материале (раздел 5):
- Ответ — `200 MaterialTextOut` = {path, status: pending|ready|failed, method, pages, description, error, text, offset, total}. `text` — не больше `limit` символов (1–100 000, по умолчанию 20 000) начиная с `offset` (по умолчанию 0; за концом — пустая строка), `total` — длина всего текста. Так же текст читает `read_material` (9.4).
- Пока текст извлекается (`pending`) и если не вышло (`failed`) — тоже `200`: `text` — null, `total` — 0, при `failed` в `error` — причина для студента. Итог приходит событием `material.ready` (9.3).
- `description` — описание картинки или null; `pages` — число страниц PDF или слайдов презентации, иначе null.
- Чужой проект, нет файла, папка или файл не из `materials/` — `404`; путь нарушает 9.8 — `422`.

**Сгенерированные файлы** (`role=generated`, сейчас это `meta.tex`) только для чтения: `PUT`, `DELETE` и `move` отвечают `403 forbidden` (9.6).

**Сборки** (с этапа 2 их ведёт воркер):
- `POST /projects/{pid}/builds` сразу отвечает `202` с `BuildOut` в статусе `queued`. Дальше: `queued` → `running` → `ok` | `error` | `timeout`.
- Файлы проекта сборка читает, когда начинается (`running`), а не когда её поставили в очередь.
- У проекта не больше одной сборки в очереди и одной идущей. Пока сборка в очереди, повторный `POST` возвращает её же: она соберёт и последние правки. Идущая сборка не прерывается — новая начнётся после неё.
- Итог — `GET /builds/{bid}`: пока `status` — `queued` или `running`, запрос повторяют раз в секунду. С B2.4 итог приходит и событием `build.finished` (9.3).
- Если файлы не менялись с прошлой успешной сборки, воркер отдаёт её PDF без компилятора (раздел 6).
- Сервис сборки недоступен — это сборка со `status=error` и сообщением в `errors`, а не HTTP-ошибка. Недоступна очередь — `500 internal`, сборка не создаётся.
- Сборка, которая идёт дольше 3 минут, получает `timeout` с сообщением в `errors`.
- `GET /projects/{pid}/builds/latest` — последняя поставленная сборка, в том числе ещё не законченная.
- `GET /projects/{pid}/builds/latest?status=ok` — последняя успешная сборка: её PDF студент видит, даже если следующая сборка упала, в том числе после перезагрузки страницы. Успешной сборки ещё не было — `404`. Другие значения `status` — `422`.

**История правок** (раздел 5):
- `GET /projects/{pid}/changesets` — changesets, в которых что-то записано, новые первыми, по `limit` (1–100, по умолчанию 50). Следующая страница — `before=<id последнего в списке>`; `has_more` — есть ли ещё. `Changeset` = {id, author, message, run_id, reverts_id, created_at, updated_at}: `updated_at` — время последней записи, `reverts_id` — какой changeset откатан этим, `message` пока всегда null. Подпись в истории («Вы, 14:02–14:09», «ИИ», «Откат») интерфейс строит из этих полей.
- `GET /changesets/{cid}/diff` — что изменил changeset, по файлам и папкам, по пути: `FileDiff` = {path, old_path, change: added|modified|deleted|moved, kind, diff, additions, deletions, too_large}:
  - `path` — путь после changeset (у удалённого — до), `old_path` — прежний путь, если файл перенесён, иначе null;
  - `diff` — unified diff текста с заголовками `--- a/<путь>` и `+++ b/<путь>` (у нового или удалённого файла — `/dev/null`), `additions` и `deletions` — сколько строк добавлено и удалено;
  - у картинок, документов и папок `diff` — null, строки — 0; перенос без правки текста — `moved`, 0 и 0, `diff` null;
  - текст больше 512 КБ до или после правки и всё, что не поместилось в 2 МБ ответа, — `too_large: true`, `diff` null, строки — 0;
  - файл, который changeset изменил и вернул как было, в список не входит.
- `POST /changesets/{cid}/revert` — возвращает файлы и папки к виду до changeset. Это новый changeset (`author=user`, `reverts_id=cid`), ответ — `201` с ним; вкладкам уходят события `file.*` с его id. Всё или ничего:
  - файл, который после changeset изменили, удалили или перенесли, мешает откату (`reason: changed`); на месте, куда нужно вернуть файл, уже другой файл (`reason: path_taken`). Тогда `409 revert_conflict` со списком в `details.files: [{path, reason}]`, и ничего не меняется;
  - файл, который уже такой, как до changeset, пропускается; если такие все — `409 revert_conflict` с пустым `files`: откатывать нечего;
  - текст и blob картинки или документа возвращаются как были — blob не копируется; материалу снова нужен разбор текста (`material_text` — `pending`);
  - папка, созданная changeset, удаляется, если в ней ничего не осталось; удалённая или перенесённая папка снова создаётся на прежнем месте;
  - откат тоже можно откатить; changeset `template` (создание проекта) и `system` (`meta.tex`) не откатываются — `403 forbidden`; проект станет больше 200 МБ — `413`.
- Changeset чужого проекта — `404`.

**Чат и прогоны агента** (раздел 8):
- `ChatMessage` = {id, role: user|assistant, run_id, status, parts, seq, created_at}. `status` у ответа ассистента — статус его прогона (`queued|running|done|failed|cancelled`), у сообщения студента — null. У каждого прогона ровно один ответ: он создаётся пустым вместе с прогоном.
- `parts` — части сообщения по порядку, как они шли во время прогона:
  - `{type: "text", text}` — текст;
  - `{type: "tool", call_id, tool, summary, ok, result}` — карточка вызова инструмента: `summary` из `run.tool_call`, `ok` и `result` — из `run.tool_result` (`result` — его `summary`); пока итога нет — null;
  - `{type: "changeset", changeset_id}` — карточка правок прогона, только если прогон что-то записал; что изменено — `GET /changesets/{cid}/diff`;
  - `{type: "error", text}` — понятная ошибка прогона.
- `seq` — номер последнего события `run.delta|tool_call|tool_result` этого прогона, которое уже вошло в `parts` (9.3); у сообщения студента — 0. Вкладка пропускает события с `seq` не больше этого; пропуск в номерах — перезапросить сообщения. После `run.finished` сообщения перезапрашивают: итоговый вид — тот, что в базе.
- `Run` = {id, status, message_id, changeset_id, error, created_at, finished_at}: `message_id` — ответ ассистента, `error` — текст ошибки при `failed`.
- `GET /projects/{pid}/messages` — последние `limit` сообщений (1–100, по умолчанию 50) по порядку, старые первыми. Более ранние — `before=<id первого на экране>`; `has_more` — есть ли ещё; id не из чата проекта — `422`. `active_run` — прогон проекта в очереди или идущий, иначе null: по нему вкладка, открытая посреди прогона, узнаёт, что ИИ работает; `status=running` — проект заблокирован.
- `POST /projects/{pid}/messages` `{text}` — текст от 1 до 10 000 символов, пробелы по краям не считаются. Ответ — `201 {message, run}`: сообщение студента и прогон в очереди. Прогон уже идёт или ждёт — `423 project_locked`; очередь недоступна — `500`, сообщение не сохраняется.
- `POST /runs/{rid}/cancel` — прогон в очереди сразу `cancelled`; идущий остановится не позже чем через 5 с, итог придёт событием `run.finished`. Ответ — `200` с прогоном; законченный прогон возвращается как есть. Прогон чужого проекта — `404`.

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
| revert_conflict | 409 |
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

У `project_locked` в `details.run_id` — прогон, который держит проект: по нему интерфейс показывает кнопку «Остановить» (`POST /runs/{rid}/cancel`):

```json
{"error": {"code": "project_locked", "message": "ИИ сейчас работает с проектом. Дождитесь ответа или остановите его",
           "details": {"run_id": "6f1c..."}}}
```

У `revert_conflict` в `details.files` — файлы, которые мешают откату (9.1):

```json
{"error": {"code": "revert_conflict", "message": "Откатить нельзя: после этих правок изменились файлы",
           "details": {"files": [{"path": "main.tex", "reason": "changed"},
                                 {"path": "figures/plot.png", "reason": "path_taken"}]}}}
```

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
| `run.delta` | `{run_id, message_id, seq, text}` |
| `run.tool_call` | `{run_id, call_id, seq, tool, summary}` |
| `run.tool_result` | `{run_id, call_id, seq, ok, summary}` |
| `run.finished` | `{run_id, status, changeset_id, usage: {tokens_in, tokens_out}}` |
| `project.locked` | `{run_id}` |
| `project.unlocked` | `{run_id}` |

`summary` — короткая строка для карточки в чате, например «Изменён sections/progress.tex (+12 −3)».

`seq` — номер события `run.delta`, `run.tool_call` и `run.tool_result` в прогоне: 1, 2, 3… без пропусков. Его ставит бэкенд; как им пользоваться — `ChatMessage.seq` (9.1). Порядок событий прогона: `project.locked` → `run.started` → `run.delta|tool_call|tool_result` → `run.finished` → `project.unlocked`. Прогон, отменённый в очереди, шлёт только `run.finished`.

`changeset_id` у `file.*` — changeset, в который попало изменение (раздел 5), `author` — его автор. Null только у событий, записанных до появления истории (B2.5): журнал хранит их до суток.

### 9.4 ProjectTools и точки входа агента (бэкенд ↔ агент; MCP повторяет тот же набор через REST)

Это внутренние Python-интерфейсы, REST от них не меняется:
- `backend/app/modules/projects/tools.py` — `ProjectTools`, `ToolContext`, `ToolError` и типы результатов. Реализация поверх сервисов — `ServiceProjectTools` в `backend/app/modules/projects/service_tools.py`: каждый вызов открывает свою короткую сессию БД, прогон минутами не держит соединение.
- `backend/app/modules/agent/contract.py` — вход и выход `run_agent` и `describe_image`. Реализует их зона ИИ (A2.1, A2.4); до этого бэкенд вызывает заглушки (B2.6, B2.7).
- Фейки для тестов без БД, Redis и воркера — `backend/tests/fake_project_tools.py` (`FakeProjectTools`) и `backend/tests/fake_run_events.py` (`FakeRunEvents`). Общие контрактные тесты `backend/tests/project_tools_contract.py` проходят и фейк, и настоящая `ProjectTools`.

```python
@dataclass(frozen=True)
class ToolContext:
    project_id: UUID
    user_id: UUID
    actor: Literal["user", "ai", "mcp"]
    changeset_id: UUID | None      # все записи попадают в этот changeset; None — реализация
                                   # создаёт свой при первой записи и пишет дальше в него

class ToolError(Exception):        # message отдаётся агенту как результат инструмента
    code: ToolErrorCode            # коды — в таблице ниже
    message: str                   # на русском: его читают модель и пользователь
    details: dict[str, JsonValue]  # например, {"count": 3} у edit_not_unique

class ProjectTools(Protocol):
    async def list_files(self) -> list[FileInfo]
    async def read_file(self, path: str, start_line: int | None = None,
                        end_line: int | None = None) -> FileText
    async def search(self, query: str, max_results: int = 50) -> list[SearchHit]
    async def write_file(self, path: str, content: str) -> FileInfo
    async def edit_file(self, path: str, old: str, new: str) -> EditResult
    async def delete_file(self, path: str) -> None
    async def compile(self) -> BuildResult
    async def list_materials(self) -> list[MaterialInfo]
    async def read_material(self, path: str, offset: int = 0,
                            limit: int = 20_000) -> MaterialText
    async def get_image(self, path: str) -> ImageData
    async def get_template_guide(self) -> TemplateGuide
    async def get_profile(self) -> ProfileOut
    # run_checks() -> list[CheckResult] — с этапа 3: метод и CheckResult добавляет B3.5
    # по спецификации проверок (T3.1)
```

Методы и результаты (модели Pydantic):
- `list_files` — все файлы и папки проекта: `FileInfo` из `projects/schemas.py`, как в дереве REST (path, kind, role, mime, size, version, updated_at).
- `read_file` — текстовый файл: `FileText` {path, version, text, start_line, end_line, total_lines}. Строки нумеруются с 1 и делятся только по `\n`; `start_line` и `end_line` включительно, по умолчанию — весь файл, диапазон за концом файла обрезается. В `text` каждая строка — номер, табуляция и сама строка.
- `search` — подстрока без учёта регистра в строках всех текстовых файлов: `SearchHit` {path, line, snippet}, snippet — строка, обрезанная до 200 символов. По пути и номеру строки, не больше `max_results`.
- `write_file` — создаёт или перезаписывает текстовый файл (новый — `role=source`, в `materials/` — `material`, 9.8); папки над ним создаются сами.
- `edit_file` — заменяет `old` на `new`. `old` должен встречаться ровно 1 раз, вхождения считаются с перекрытиями. `EditResult` {file: FileInfo, line} — line: строка, с которой началась замена. Чтение и запись — одна транзакция: между ними файл никто не изменит.
- `delete_file` — удаляет файл или папку со всем содержимым, как `DELETE` в REST.
- `compile` — собирает проект и ждёт итог: `BuildResult` {status: ok|error|timeout, build_id, pages, errors: list[BuildError], warnings_count}. В `errors` — ошибки и предупреждения (поле severity), как в `BuildOut`. Ждёт не дольше 2 минут: не дождался — `status=timeout` с сообщением в `errors`, а сборка идёт дальше и её итог придёт событием.
- `list_materials` — файлы из `materials/`: `MaterialInfo` {path, mime, size, status: pending|ready|failed, description}; description — описание картинки или null.
- `read_material` — извлечённый текст материала: `MaterialText` {text, offset, total} — не больше `limit` символов начиная с `offset` и длина всего текста.
- `get_image` — картинка .png, .jpg или .jpeg: `ImageData` {data: bytes, mime}.
- `get_template_guide` — `TemplateGuide` {slug, title, discipline, main_file, sections, ai_rules, fields, macros}: sections — `TemplateSection` из `templates/schemas.py` (id, title, file, required, guide); fields — поля проекта {key, label, value, macro}; macros — макросы класса из 9.6 {usage, description}.
- `get_profile` — `ProfileOut` из `profiles/schemas.py`, как `GET /profile`.

`BuildError = {file, line, message, context, severity}` — модель из `builds/schemas.py`. В `context` — до 10 строк до и после места ошибки, с номерами строк.

Все реализации ведут себя одинаково:
- Пути проверяет `validate_path` из `projects/paths.py`, типы файлов и лимиты — по 9.8. Файл `role=generated` и папку с ним не записать, не изменить и не удалить (9.6).
- Агент (`actor=ai`) материалы только читает: `write_file`, `edit_file` и `delete_file` в `materials/` и самой папки `materials` — `forbidden`. Материалы — то, что принёс студент (код, вывод программы, методичка), и ИИ не должен выдать придуманный вывод за них. Листинг для отчёта агент кладёт в обычную папку. Через MCP пишет сам студент — ему можно.
- Все записи идут в changeset из `ToolContext` с `author` = `actor` (раздел 5) и шлют те же события `file.*`, что правки через REST.
- Ошибка, которую модель может исправить или объяснить пользователю, — `ToolError`. Остальные исключения (сбой базы, ошибка в коде) не перехватываются: прогон завершается со статусом failed.
- Если ошибка та же, что в REST, код совпадает с 9.2: через MCP агент получает те же коды.

| code | когда | ошибка сервиса файлов |
|---|---|---|
| `not_found` | нет файла, папки или материала; проект удалён | 404 not_found |
| `already_exists` | путь занят: на этом месте папка или над файлом — файл, а не папка | 409 already_exists |
| `forbidden` | файл создаётся автоматически (`meta.tex`) или лежит в этой папке; агент меняет материал | 403 forbidden |
| `payload_too_large` | текст больше 2 МБ или проект станет больше 200 МБ | 413 payload_too_large |
| `unsupported_file_type` | тип файла не из 9.8; `read_file` — файл не текстовый; `get_image` — файл не картинка | 415 unsupported_file_type |
| `invalid_path` | путь нарушает правила 9.8 | 422: `InvalidPathError` из `validate_path` |
| `validation_error` | остальные неверные аргументы: нулевой символ в тексте, пустые `old` или `query`, `start_line` < 1, `end_line` < `start_line`, отрицательный `offset`, `limit` или `max_results` < 1 | 422 validation_error |
| `project_locked` | проект занят: идёт другой прогон | 423 project_locked |
| `edit_not_found` | `old` не найден | — |
| `edit_not_unique` | `old` найден больше 1 раза; число вхождений — в `details.count` | — |
| `material_not_ready` | текст материала ещё извлекается или не извлёкся (status pending или failed) | — |
| `internal` | сбой сервиса, о котором нужно сказать пользователю, например сборка недоступна | 500 internal |

#### Точки входа агента

```python
@dataclass(frozen=True)
class RunRequest:                      # вход run_agent
    history: Sequence[HistoryMessage]  # сообщения чата по порядку, последнее — запрос пользователя
    context: ToolContext
    tools: ProjectTools
    events: RunEvents
    cancel: asyncio.Event              # отмена: бэкенд взводит по POST /runs/{rid}/cancel
    max_tokens: int                    # лимит токенов на прогон, вход и выход вместе
    user_key: SecretStr | None = None  # свой ключ LLM пользователя (B3.1); без него — ключ сервиса

class RunEvents(Protocol):             # run_id, message_id и seq к событиям добавляет бэкенд
    async def delta(self, text: str) -> None                                   # run.delta
    async def tool_call(self, call_id: str, tool: str, summary: str) -> None   # run.tool_call
    async def tool_result(self, call_id: str, ok: bool, summary: str) -> None  # run.tool_result

class RunAgent(Protocol):
    async def __call__(self, request: RunRequest) -> RunResult: ...

class DescribeImage(Protocol):
    async def __call__(self, data: bytes, mime: str, *,
                       user_key: SecretStr | None = None) -> ImageDescription: ...
```

- `HistoryMessage` — {role: user|assistant, text}.
- `ModelUsage` — {model, tokens_in, tokens_out, cost: Decimal}.
- `RunResult` — {status: done|failed|cancelled, text, error, usage: ModelUsage}: text — ответ ассистента (при отмене — то, что успело прийти); error — сообщение для пользователя при failed, иначе null.
- `ImageDescription` — {text, usage: ModelUsage}.

Правила:
- `run.started`, `run.finished`, `project.locked` и `project.unlocked` шлёт бэкенд. Агент шлёт только `run.delta`, `run.tool_call` и `run.tool_result` через `RunEvents`; `call_id` — id вызова инструмента у модели.
- Отмену агент проверяет между шагами и во время стрима и возвращает `status=cancelled`. Правки до отмены остаются в changeset прогона — их можно откатить.
- Сбой модели и превышение `max_tokens` — не исключение, а `status=failed` с понятным `error`. `ToolError` возвращается модели как результат инструмента. Другие исключения выходят из `run_agent`: бэкенд помечает прогон failed с общим сообщением.
- `describe_image` при сбое модели бросает исключение — бэкенд (B2.7) оставляет описание пустым.
- Ключ пользователя и история чата не попадают в логи и repr.

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
  - key: work_type
    label: "Вид работы"
    type: select
    options: ["Лабораторная работа", "Практическая работа"]
    default: "Лабораторная работа"
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

Поля (`fields`):
- `key` — до 50 символов: слова из строчных латинских букв через одиночный `_`, например `lab_number`. `_` в начале и в конце, два `_` подряд и цифры запрещены: из ключа получается макрос `\bbtLabNumber` (9.6), а цифры в имени макроса TeX недопустимы. Ключи встроенных макросов 9.6 (`last_name`, `group`, `year`, `title_page` и т. п.) заняты.
- `type: select` — обязателен непустой список `options`, значение поля — один из них. У остальных типов `options` нет.
- `required` по умолчанию `false`. `default` — того же типа, что поле, у `select` — один из `options`. Если поле не передано при создании проекта, сохраняется `default`.
- Длина значения: у `string` и `select` — до 200 символов (как у полей профиля), у `text` — до 10 000. Те же лимиты у `default` и у каждого из `options`. Значение длиннее — `422 validation_error` с `type: string_too_long`, в `loc` — `body`, `fields` и ключ поля.

### 9.6 meta.tex и макросы класса

`meta.tex` генерирует бэкенд: `role=generated`. Он пересоздаётся при изменении профиля или полей проекта. Все значения экранируются: `\ & % $ # _ { } ~ ^`.

Файлы `role=generated` меняет только бэкенд. Записать, удалить или перенести такой файл через REST API и `ProjectTools` нельзя — как и папку, в которой он лежит: `403 forbidden` «Файл создаётся автоматически» (для папки в тексте назван этот файл). Запрет проверяется раньше версии: `PUT` с устаревшим `If-Match` или с `If-None-Match: *` тоже получает 403, а не 412 или 409. Создать файл или папку на месте такого файла нельзя, как и на любом занятом пути, — `409 already_exists`.

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
→ 200 {"status": "ok", "version": "2025.1+3f9a0c51d2e4b7a8"}
```

- `version` в `/health` — версия сборочного окружения для кэша сборок (раздел 6): `COMPILER_VERSION` из образа, `+` и 16 символов sha256 от путей и содержимого файлов общего класса. Вне образа вместо `COMPILER_VERSION` — `dev`.

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
- Запрещены и спецсимволы TeX: `% # ~ $ & ^ { }`, обратная кавычка и `"`. Файл с `% # { } "` в имени не подключить через `\input`, `\includegraphics` или `\lstinputlisting`, а остальные ломают текст документа, если имя файла попадёт в него.
- Максимальная длина пути — 255 символов, сегмента — 100 символов и не больше 255 байт в UTF-8 (предел имени файла в Linux).
- Материалы лежат в `materials/`, `meta.tex` — в корне проекта. Роль файла задаёт путь: в `materials/` (на любой глубине) — `material`, остальные файлы пользователя — `source`. Так при загрузке, записи текста и переносе: файл, перенесённый в `materials/` или из неё, меняет роль. У папок роль всегда `source`.
- Лимиты:
  - текстовый файл — до 2 МБ, загружаемый — до 20 МБ; за один запрос загрузки — до 100 файлов и 200 МБ;
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
  - backend: ruff, pytest с Postgres и Redis, свежесть `openapi.json`;
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
