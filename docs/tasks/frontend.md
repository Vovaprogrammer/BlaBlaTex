# Фронтенд — задачи

**Владелец:** Провкин Алексей. **Ревьюер по умолчанию:** Чистяков Владимир; UX смотрит Вершинина Кристина.
**Зона:** `frontend/`.
**Перед любой задачей** агент читает `AGENTS.md`, `docs/architecture.md` (разделы 9.1–9.3 и 10 — всегда, остальное по «Контексту») и `docs/tasks/README.md`.

Общие правила зоны:
- Интерфейс простой: центр — чат, слева — дерево, справа — PDF. LaTeX — вкладка, а не главное. Без декоративных градиентов. Светлая и тёмная тема — через токены shadcn.
- Все тексты на русском и понятны студенту без знания LaTeX.
- До готовности эндпоинта работаем на MSW-моках, которые строго соответствуют `backend/openapi.json`.

---

## Этап 0 — подготовка

### F0.1 Скелет фронтенда
**Ветка:** `chore/f0.1-frontend-skeleton` · **Зависит от:** B0.1 · **Контекст:** 3, 10

**Коммиты:**
1. `chore(frontend): vite, react 19 and strict typescript with pnpm`
2. `chore(frontend): tailwind v4 and shadcn/ui with light and dark theme`
3. `chore(frontend): eslint, prettier, vitest and testing-library`
4. `chore(frontend): feature folders, router skeleton and dev proxy to :8000`
5. `ci(frontend): lint, typecheck, test and build workflow`

**Готово, когда:** `pnpm dev` открывает пустой каркас с переключением темы; CI зелёный.

### F0.2 Вайрфреймы (не код)
**Ветка:** `docs/f0.2-wireframes`

Экраны (Miro или Figma):
1. вход и регистрация;
2. профиль;
3. список проектов;
4. мастер нового проекта (тип → шаблон → поля → материалы);
5. рабочее окно (дерево | чат + вкладки | PDF);
6. настройки (ключ ИИ, токены MCP);
7. мобильная раскладка рабочего окна.

Согласовать с командой до начала этапа 1.

**Коммиты:**
1. `docs(design): wireframes v1` — PNG и ссылка в `docs/design/`.

---

## Этап 1 — скелет

### F1.1 Каркас приложения и API-клиент
**Ветка:** `feat/f1.1-app-shell` · **Зависит от:** B1.0 (`openapi.json`) · **Контекст:** 9.1, 9.2, 10

**Коммиты:**
1. `feat(api): generated types and typed fetch client` — `pnpm gen:api` (`openapi-typescript` → `src/api/schema.d.ts`), клиент `openapi-fetch`. `credentials: 'include'`, заголовок `X-CSRF-Protection: 1` на небезопасных методах; ошибки разбираются по формату 9.2 в класс `ApiError`.
2. `feat(app): query client, error boundary and toasts` — 401 → редирект на вход; остальные ошибки → тост с `message` от сервера.
3. `feat(app): MSW mocks for sprint 1 endpoints` — включаются через `VITE_USE_MOCKS=1`, данные правдоподобные.
4. `feat(app): layout, routes and auth guard` — `/login`, `/register`, `/profile`, `/projects`, `/projects/:id`, `/settings`.

**Готово, когда:** фронт целиком работает на моках; переключение на настоящий API — одной переменной.

### F1.2 Вход, регистрация, профиль
**Ветка:** `feat/f1.2-auth-ui` · **Зависит от:** F1.1

**Коммиты:**
1. `feat(auth): login and register pages with validation` — `react-hook-form` + `zod`; обязательный чекбокс согласия на обработку персональных данных со ссылкой на текст (T3.3, пока заглушка).
2. `feat(auth): session bootstrap via /auth/me and logout`
3. `feat(profile): profile form` — фамилия, имя, отчество, группа, факультет, кафедра. Подсказка: «Эти данные попадут на титульный лист». После регистрации — сразу сюда.

**Готово, когда:** ошибки сервера показываются у нужных полей; после обновления страницы сессия сохраняется.

### F1.3 Проекты
**Ветка:** `feat/f1.3-projects` · **Зависит от:** F1.1

**Коммиты:**
1. `feat(projects): projects list with empty state`
2. `feat(projects): create project dialog with dynamic template fields` — список шаблонов из `GET /templates`. Форма строится по `fields[]` (типы `string|int|text|select`, `required`, `default`).
3. `feat(projects): rename and delete project` — удаление с подтверждением.

**Не делать:** полный мастер с материалами — это F2.5.

### F1.4 Рабочее окно и дерево файлов
**Ветка:** `feat/f1.4-workspace` · **Зависит от:** F1.1 · **Контекст:** 9.1, 9.8, 10

**Коммиты:**
1. `feat(workspace): three resizable panels with persisted sizes` — `react-resizable-panels`; размеры в `localStorage` (try/catch). Уже 768 px — вкладки «Файлы / Чат / PDF».
2. `feat(workspace): file tree with create, rename, move and delete` — `react-arborist`, drag-and-drop, контекстное меню. Секция «Материалы» — отдельно (пока пустая). `meta.tex` помечен как «создаётся автоматически», только чтение.
3. `feat(workspace): tabs in center panel` — первая вкладка «Чат» (пока заглушка), файлы открываются вкладками и закрываются.

**Готово, когда:** ошибки валидации путей от сервера понятны пользователю, например «Имя не может начинаться с точки».

### F1.5 Редактор
**Ветка:** `feat/f1.5-editor` · **Зависит от:** F1.4

**Коммиты:**
1. `feat(editor): CodeMirror 6 with LaTeX highlighting` — `@uiw/react-codemirror`, режим `stex` из `@codemirror/legacy-modes`, номера строк, поиск, перенос строк.
2. `feat(editor): autosave with debounce and version conflicts` — PUT через 1,5 с после паузы с `If-Match`. На 412 — окно «Файл изменился»: показать diff, выбрать «Взять версию с сервера» или «Оставить мою». Текст пользователя не теряется никогда.
3. `feat(editor): open file at line` — API для перехода к `path:line`; нужен для ошибок сборки и SyncTeX.

**Готово, когда:** файл на 3000 строк редактируется без задержек; тест на сценарий конфликта.

### F1.6 PDF и сборка
**Ветка:** `feat/f1.6-pdf` · **Зависит от:** F1.4 · **Контекст:** 9.1

**Коммиты:**
1. `feat(pdf): react-pdf viewer with lazy pages and zoom` — worker pdf.js настроен для Vite.
2. `feat(pdf): compile button, build status and preserved scroll` — после пересборки остаёмся на той же странице и позиции; скачать PDF.
3. `feat(pdf): build errors list with jump to file and line`

**Готово, когда:** сценарий этапа 1 проходит от начала до конца: регистрация → проект → правка → PDF.

---

## Этап 2 — ИИ в чате

### F2.1 События проекта (SSE)
**Ветка:** `feat/f2.1-events` · **Зависит от:** B2.4 · **Контекст:** 9.3

**Коммиты:**
1. `feat(events): useProjectEvents hook with reconnect` — `@microsoft/fetch-event-source`, `Last-Event-ID`, экспоненциальная пауза между переподключениями; типы событий — строго по 9.3.
2. `feat(events): invalidate queries on file and build events` — открытый файл без локальных правок обновляется сам; с правками — показывается конфликт (как в F1.5).

### F2.2 Чат
**Ветка:** `feat/f2.2-chat` · **Зависит от:** F2.1; API — B2.6 (до этого моки) · **Контекст:** 9.1, 9.3

**Коммиты:**
1. `feat(chat): message list with markdown, math and streaming` — `react-markdown` + KaTeX. `run.delta` дописывает текст в текущее сообщение; автопрокрутка, пока пользователь не прокрутил вверх.
2. `feat(chat): composer with attachments and stop button` — файлы, вставленные или перетащенные в поле, загружаются в `materials/`; Enter — отправить, Shift+Enter — новая строка.
3. `feat(chat): history loading and run status` — «Думает…», «Собирает PDF…», ошибка прогона с понятным текстом.

### F2.3 Действия агента: карточки, diff, откат
**Ветка:** `feat/f2.3-agent-actions` · **Зависит от:** F2.2; API — B2.5

**Коммиты:**
1. `feat(chat): tool call cards collapsed by default` — по `run.tool_call`/`run.tool_result`: иконка, `summary`, раскрытие подробностей.
2. `feat(chat): changeset summary card with diff viewer` — «Изменено 2 файла, +24 −3» → окно с `@codemirror/merge` по файлам.
3. `feat(chat): revert changeset with confirmation` — 409 → показать, какие файлы мешают откату.

### F2.4 Материалы
**Ветка:** `feat/f2.4-materials` · **Зависит от:** F1.4; API — B2.2

**Коммиты:**
1. `feat(materials): upload by drag-and-drop into materials section` — прогресс загрузки; ошибки 413 и 415 — понятным текстом с лимитом.
2. `feat(materials): preview for pdf, images, text and code with extraction status` — значок «обрабатывается / готово / ошибка» по `material.ready`.

### F2.5 Мастер нового проекта
**Ветка:** `feat/f2.5-wizard` · **Зависит от:** F1.3, F2.4, F2.2

**Коммиты:**
1. `feat(wizard): steps — type, template, fields, materials` — тип «Лабораторная» доступен, «ВКР / Статья / Презентация» помечены «скоро». Поля предзаполнены из прошлого проекта той же дисциплины, если он есть.
2. `feat(wizard): create project and start first run` — после создания открывается рабочее окно, и в чат уходит заготовленное сообщение «Сделай отчёт по загруженным материалам».

### F2.6 Режим «только чтение» во время работы агента
**Ветка:** `feat/f2.6-run-lock` · **Зависит от:** F2.1, F1.5

**Коммиты:**
1. `feat(workspace): read-only editor and banner while agent is running` — по `project.locked/unlocked` и ответу 423; на баннере кнопка «Остановить».

---

## Этап 3 — MVP

### F3.1 Подтверждение плана отчёта
**Ветка:** `feat/f3.1-plan` · **Зависит от:** A3.1 · **Контекст:** 8, 9.1

**Коммиты:**
1. `feat(plan): plan view — sections with assigned materials`
2. `feat(plan): edit and confirm plan` — менять порядок, удалять, переназначать материалы; «Подтвердить и написать отчёт».

### F3.2 Настройки: ключ ИИ и использование
**Ветка:** `feat/f3.2-settings-ai` · **Зависит от:** B3.1

**Коммиты:**
1. `feat(settings): own LLM key — add, replace, remove` — ключ отображается как `••••last4`.
2. `feat(settings): usage and quota indicator` — в шапке; при 429 `quota_exceeded` — объяснение и ссылка на настройки ключа.

### F3.3 Экспорт и полировка
**Ветка:** `feat/f3.3-polish` · **Зависит от:** B3.2

**Коммиты:**
1. `feat(projects): download PDF and sources zip`
2. `feat(ui): empty, loading and error states across screens`
3. `feat(ui): first-run hints in workspace` — 3–4 подсказки, можно закрыть навсегда.

### F3.4 Быстрые действия
**Ветка:** `feat/f3.4-quick-actions` · **Зависит от:** A3.4

**Коммиты:**
1. `feat(chat): quick actions above composer` — это обычные сообщения агенту. Набор лежит в `src/features/chat/quick-actions.ts`, тексты — из A3.4. Действия, которым нужен выбор (например, «Сократи раздел…»), сначала спрашивают раздел.

### F3.5 E2E-тесты
**Ветка:** `test/f3.5-e2e` · **Зависит от:** A2.5, коммит 3 (детерминированная тестовая модель), B3.4

**Коммиты:**
1. `test(e2e): playwright setup against compose stack in test LLM mode`
2. `test(e2e): register → create project → upload → chat → PDF`
3. `ci(e2e): run e2e on PR to main`

---

## Этап 4 — русло 2

### F4.1 Токены и страница подключения MCP
**Ветка:** `feat/f4.1-mcp-settings` · **Зависит от:** B4.1, A4.3

**Коммиты:**
1. `feat(settings): personal API tokens — create once, list, revoke`
2. `feat(settings): MCP setup page with copyable commands` — Claude Code (плагин), opencode, Cursor; тексты — из `docs/mcp.md` (A4.4).

### F4.2 SyncTeX
**Ветка:** `feat/f4.2-synctex` · **Зависит от:** B4.3

**Коммиты:**
1. `feat(pdf): click in PDF opens source line` — Ctrl+клик.
2. `feat(editor): show cursor position in PDF`

### F4.3 Исправления по пилоту
Задачи из GitHub Issues с меткой `pilot`. Каждая — отдельный PR.

---

## Этапы 5–7 — ВКР (детализируются позже)

- **F5:**
  - панель оглавления для больших документов;
  - импорт DOCX в мастере;
  - библиография: добавление источника по DOI/ISBN.
- **F6:**
  - кабинет преподавателя: группы, отправки, статусы;
  - комментарии к строке и к месту в PDF;
  - «Отправить на проверку».
- **F7:**
  - сравнение версий: построчно и PDF `latexdiff`;
  - ИИ-сводка изменений;
  - отчёт нормоконтроля.
