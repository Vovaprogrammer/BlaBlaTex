# ИИ, шаблонный модуль и MCP — задачи

**Зона:**
- в `backend/app/modules/`: `agent`, `templates`, `checks` и извлечение текста в `materials`;
- `tools/llm-bench/`, `eval/`, `mcp/`.

**Перед любой задачей** агент читает `AGENTS.md`, `docs/architecture.md` (разделы 8 и 9.4 — всегда, остальное по «Контексту») и `docs/tasks/README.md`.

Общие правила зоны:
- В тестах — только тестовая модель PydanticAI или `FakeProjectTools`, никаких сетевых вызовов к провайдерам.
- API PydanticAI и MCP SDK проверяй по документации установленной версии: они меняются.
- Промпты — файлы в `backend/app/modules/agent/prompts/`. Любое изменение промпта — отдельный коммит, в PR — результаты eval до и после.
- Агент не выдумывает факты. Числа, результаты и вывод программ — только из материалов; источники — только из инструментов поиска.
- Реальные методички и отчёты студентов не попадают в репозиторий. Eval читает их из `EVAL_DATA_DIR` вне репозитория.

---

## Этап 0 — подготовка

### A0.1 Бенчмарк LLM-провайдеров
**Ветка:** `feat/a0.1-llm-bench` · **Зависит от:** T0.2 (3–5 комплектов) · **Контекст:** 8

**Коммиты:**
1. `feat(tools): llm-bench harness for OpenAI-compatible providers` — `tools/llm-bench/`. Конфиг: список `{name, base_url, api_key_env, model}`; ключи только из `.env`.
2. `feat(tools): bench scenarios` — три сценария:
   - **tool calling:** дан `.tex` с известной ошибкой и инструменты `read_file/edit_file/compile` на фейке, 10 прогонов, считаем успехи;
   - **раздел отчёта:** «Ход работы» по материалу комплекта;
   - **vision:** описание скриншота с выводом программы.

   Для каждого прогона: время, токены, цена.
3. `docs(adr): 0002 LLM provider and model roles` — таблица результатов, оценка текста вслепую от Вершининой (1–5), выбор моделей `main`/`fast`/`vision` и запасного провайдера.

Кандидаты:
- Yandex AI Studio (OpenAI-совместимый API, function calling);
- агрегаторы с оплатой в рублях и OpenAI-совместимым `base_url`;
- GigaChat;
- OpenRouter — если хостинг за рубежом (связано с ADR 0003).

**Готово, когда:** решение принято командой и записано в ADR.

---

## Этап 1 — скелет

### A1.1 LLM-слой
**Ветка:** `feat/a1.1-llm-layer` · **Зависит от:** B1.1, A0.1 · **Контекст:** 4, 5, 8

**Коммиты:**
1. `feat(llm): provider settings and model roles` — настройки `LLM_PROVIDERS` (base_url, ключ, модели по ролям), выбор провайдера по умолчанию, таймауты.
2. `feat(llm): model factory for OpenAI-compatible providers with fallback` — `get_model(role, user_key=None)`. Если основной провайдер вернул 5xx или таймаут — переключаемся на запасной.
3. `feat(llm): usage recording per run and per user` — таблица `usage` + миграция по разделу 5; функция `record_usage(user_id, run_id, tokens_in, tokens_out, cost)`; цены моделей — в конфиге.

**Готово, когда:** смена провайдера — только `.env`; ключи не попадают в логи (есть тест); B3.1 может опираться на `usage`.

### A1.2 Модуль шаблонов
**Ветка:** `feat/a1.2-templates-module` · **Зависит от:** T1.1 (вместе), B1.3 (для коммита 4) · **Контекст:** 7, 9.5, 9.6

**Коммиты:**
1. `feat(templates): TemplateManifest model and JSON Schema export` — Pydantic-модель строго по 9.5. Команда экспорта пишет `templates/_schema/template.schema.json`; CI проверяет свежесть. Это контракт с зоной шаблонов (T1.1).
2. `feat(templates): registry loads and validates templates at startup` — все `templates/*/template.yaml`. Ошибка валидации называет файл и поле. Вызывается в тесте CI.
3. `feat(templates): GET /templates and /templates/{slug}` — отдаются поля, разделы и описание; `ai_rules` наружу не отдаются.
4. `feat(templates): create project from template` — `POST /projects` с `template_slug` копирует файлы шаблона (кроме `template.yaml` и `meta.sample.tex`) через сервис файлов в changeset `author=template`; поля проверяются по манифесту.
5. `feat(templates): meta.tex generation with LaTeX escaping` — макросы по 9.6; пересоздание при изменении профиля или `fields`.

   Тест на экранирование: «Ёлкин-Палкин & Co_1 #2 {x} ~ ^ \ %».

**Готово, когда:** в сценарии этапа 1 проект создаётся из `mtuci-lab`, и титульник собирается с данными профиля.

### A1.3 Извлечение текста из материалов (библиотека)
**Ветка:** `feat/a1.3-extraction` · **Зависит от:** B0.1

**Коммиты:**
1. `feat(materials): text extraction for pdf, docx, pptx, xlsx via markitdown` — `extract(path, mime) -> Extracted{text, pages, method}`; маркеры страниц для PDF.
2. `feat(materials): passthrough for code and text, size caps and failures` — текст длиннее лимита обрезается с пометкой; ошибка — понятное сообщение, а не трейсбек.

**Готово, когда:** тесты на маленьких синтетических файлах проходят, реальные методички в репозитории не нужны.
**Не делать:** запуск в воркере — это A2.4.

---

## Этап 2 — ИИ в чате

### A2.1 Ядро агента
**Ветка:** `feat/a2.1-agent-core` · **Зависит от:** B2.1 (интерфейс + фейк), A1.1; для коммитов 2–3 — B2.3, B2.4 · **Контекст:** 8, 9.3, 9.4

**Коммиты:**
1. `feat(agent): agent with tools bound to ProjectTools` — инструменты 1:1 с методами `ProjectTools` (кроме `run_checks`). Описания инструментов — на русском и конкретные; `ToolError.message` возвращается модели как результат.
2. `feat(agent): run loop with usage limits, cancellation and events` — стриминг в события `run.*` по 9.3. Лимит токенов на прогон берётся из конфига. Отмена проверяется между шагами и во время стрима. Итог прогона — в `agent_runs` и `usage`.
3. `feat(agent): taskiq job run_agent(run_id)` — точка входа для B2.6: загружает историю чата (последние N сообщений), создаёт `ToolContext(actor="ai", changeset_id=...)` и запускает агента.

**Готово, когда:** тесты на фейке и тестовой модели показывают, что агент вызывает `edit_file` и `compile`; отмена срабатывает; при превышении лимита прогон завершается со статусом `failed` и понятным сообщением.

### A2.2 Цикл исправления ошибок сборки
**Ветка:** `feat/a2.2-fix-loop` · **Зависит от:** A2.1 · **Контекст:** 6, 8

**Коммиты:**
1. `feat(agent): compact compile results for the model` — только ошибки (до 5 штук) с контекстом ±10 строк, без полного лога.
2. `feat(agent): fix loop policy` — не больше 4 итераций. Одна и та же ошибка дважды подряд — остановка с честным сообщением пользователю: что не получилось и где.
3. `test(agent): broken documents fixture set` — 10 сломанных `.tex` (незакрытая скобка, неизвестная команда, `_` вне математики, отсутствующая картинка и т. п.) и сценарии тестовой модели.

**Готово, когда:** на реальном провайдере (ручной прогон, результат — в PR) чинится не меньше 8 из 10.

### A2.3 Промпты v1
**Ветка:** `feat/a2.3-prompts-v1` · **Зависит от:** A2.1, A1.2, T1.2 (справочник макросов) · **Контекст:** 7, 8, 9.5, 9.6

**Коммиты:**
1. `feat(agent): prompt files layout and loader` — `prompts/system.md`, `prompts/report.md` и т. д. Jinja2 для подстановок; промпты не живут в Python-строках.
2. `feat(agent): template guide and profile injection` — разделы, `guide`, `ai_rules` шаблона и справочник макросов класса из `docs/templates.md`.
3. `feat(agent): core rules` — факты только из материалов; `edit_file` вместо переписывания; только макросы класса; `meta.tex` не трогать; отвечать пользователю по-русски и коротко.

### A2.4 Обработка материалов в воркере
**Ветка:** `feat/a2.4-materials-pipeline` · **Зависит от:** A1.3, B2.2, B2.3 · **Контекст:** 5, 8, 9.3

**Коммиты:**
1. `feat(materials): extraction job on upload and material.ready event`
2. `feat(materials): screenshot description with vision model` — включается конфигом; описание сохраняется в `material_text.description`; квота учитывается.
3. `feat(agent): material tools use extracted text and descriptions` — `list_materials` и `read_material` отдают статус и описание.

### A2.5 Eval v0
**Ветка:** `feat/a2.5-eval` · **Зависит от:** A2.1, T2.4 (данные)

**Коммиты:**
1. `feat(eval): runner over cases from EVAL_DATA_DIR` — формат кейса — `eval/cases.example.yaml` (вместе с Вершининой). Прогон: создать проект, загрузить материалы, запустить агента, собрать PDF.
2. `feat(eval): metrics report` — собралось или нет, число итераций исправления, все ли обязательные разделы на месте, чек-лист кейса, токены и цена. Результат — markdown-таблица.
3. `feat(eval): deterministic scripted model for e2e tests` — режим `LLM_TEST_MODE=scripted`: заранее записанный сценарий без сети. Нужен для F3.5.

---

## Этап 3 — MVP

### A3.1 План отчёта
**Ветка:** `feat/a3.1-report-plan` · **Зависит от:** A2.3 · **Контекст:** 8, 9.1

**Коммиты:**
1. `feat(agent): ReportPlan schema and plan generation` — структурированный вывод: разделы шаблона, для каждого — назначенные материалы и короткая заметка «что будет написано». Материалы, которым не нашлось места, — отдельным списком.
2. `feat(agent): plan endpoints — create, update, confirm` — эндпоинты по 9.1. После подтверждения запускается прогон генерации.

### A3.2 Генерация по разделам
**Ветка:** `feat/a3.2-section-generation` · **Зависит от:** A3.1

**Коммиты:**
1. `feat(agent): section-by-section generation from confirmed plan` — раздел за разделом, сборка в конце и после каждого крупного раздела.
2. `feat(agent): context budget for materials` — в контекст раздела попадают только назначенные материалы; длинные — кусками через `read_material(offset, limit)`.

### A3.3 Проверки v1
**Ветка:** `feat/a3.3-checks` · **Зависит от:** T3.1 (спецификация) · **Контекст:** 8, 9.4

**Коммиты:**
1. `feat(checks): deterministic checks for lab reports` — по `docs/checks.md`:
   - обязательные разделы не пустые;
   - на каждый рисунок, таблицу и листинг есть ссылка в тексте;
   - у всех есть подписи;
   - нет заглушек вроде «TODO» и «Lorem»;
   - сборка без ошибок.
2. `feat(agent): run_checks tool and checks summary` — агент запускает проверки в конце прогона и пишет короткую сводку; эндпоинт для UI.

### A3.4 Быстрые действия и настройка промптов
**Ветка:** `feat/a3.4-quick-actions-tuning` · **Зависит от:** A2.5

**Коммиты:**
1. `docs(agent): quick action texts` — 5–7 формулировок для F3.4 («Сократи раздел…», «Добавь таблицу из…», «Добавь скриншот…», «Исправь ошибки сборки», «Перепиши проще»). Каждая проверена на eval.
2. `chore(agent): prompt tuning by eval results` — в PR: таблица метрик до и после.

---

## Этап 4 — русло 2 (MCP)

### A4.1 Пакет blablatex-mcp
**Ветка:** `feat/a4.1-mcp-skeleton` · **Зависит от:** B4.1 · **Контекст:** 9.1, 11

**Коммиты:**
1. `feat(mcp): package skeleton with stdio server` — `mcp/blablatex-mcp/`, uv, entry point `blablatex-mcp`, версия MCP SDK зафиксирована точно.
2. `feat(mcp): REST client with token and base URL from env` — `BLABLATEX_URL` (по умолчанию — прод), `BLABLATEX_TOKEN`; ошибки API превращаются в понятный текст для модели.

### A4.2 Инструменты MCP
**Ветка:** `feat/a4.2-mcp-tools` · **Зависит от:** A4.1 · **Контекст:** 9.4, 11

**Коммиты:**
1. `feat(mcp): profile, templates and project tools` — `get_profile`, `list_templates`, `list_projects`, `create_project(template, fields, title)`, `get_template_guide`.
2. `feat(mcp): upload_materials restricted to working directory` — только файлы внутри текущей рабочей папки (после разрешения симлинков). Отклоняются скрытые файлы, `.env`, `*.key`, `*.pem`; лимиты 9.8.
3. `feat(mcp): file and compile tools with compact outputs` — `list_files`, `read_file(range)`, `edit_file`, `write_file`, `compile`; вывод каждого инструмента не больше ~5 тыс. токенов.
4. `feat(mcp): download_pdf into working directory` — по умолчанию `reports/<slug>.pdf`; не перезаписывает без `overwrite=true`.

**Готово, когда:** тесты на клиенте MCP SDK против моков API; попытки загрузить `../x`, `~/.ssh/id_rsa` и `.env` отклоняются.

### A4.3 Плагин Claude Code
**Ветка:** `feat/a4.3-claude-plugin` · **Зависит от:** A4.2, T4.1 (текст skill)

Структуру плагина проверяй по документации Claude Code (Plugins, MCP).

**Коммиты:**
1. `feat(plugin): plugin manifest with userConfig` — `mcp/claude-plugin/.claude-plugin/plugin.json`: `api_token` (`"sensitive": true`), `server_url`.
2. `feat(plugin): .mcp.json launching blablatex-mcp via uvx` — `uvx --from git+https://github.com/Vovaprogrammer/BlaBlaTex#subdirectory=mcp/blablatex-mcp blablatex-mcp`; переменные — из `${user_config.*}`.
3. `feat(plugin): lab-report skill` — `skills/lab-report/SKILL.md`, текст от Вершининой (T4.1).
4. `feat(plugin): marketplace manifest` — чтобы ставилось командой `/plugin` из репозитория.

### A4.4 Проверка и документация
**Ветка:** `docs/a4.4-mcp-docs` · **Зависит от:** A4.3

**Коммиты:**
1. `docs(mcp): setup guide for Claude Code, opencode and Cursor` — `docs/mcp.md`; эти тексты использует F4.1.
2. `test(mcp): end-to-end scenario script against staging` — сценарий «создай проект → загрузи материалы → напиши разделы → собери → скачай PDF» и его результат в PR.

---

## Этапы 5–7 — ВКР (детализируются позже)

- **A5:**
  - инструменты для большого документа: оглавление с диапазонами строк, поиск, чтение по диапазонам;
  - импорт DOCX через Pandoc (вместе с B5);
  - библиография: поиск по DOI/ISBN/названию через Crossref и OpenAlex, запись в `.bib`; агент не добавляет источники без инструмента.
- **A6:** ИИ-рецензия черновика как рекомендации, отдельно от нормоконтроля.
- **A7:**
  - ИИ-сводка изменений между отправками;
  - ИИ-проверки стиля как рекомендации;
  - MCP-инструменты для ВКР.
