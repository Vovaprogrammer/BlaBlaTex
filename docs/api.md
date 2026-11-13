# API BlaBlaTex для агентов и скриптов

Руководство для тех, кто пишет MCP-клиент, плагин для своего агента (Codex, Cursor, opencode, Antigravity, Claude Code и других) или скрипт. Студенту оно не нужно: готовый сервер `blablatex-mcp` делает всё сам.

Здесь — как войти по личному токену, как пройти путь от пустого проекта до PDF, что делать с каждой ошибкой и какие есть лимиты. Подробности каждого запроса — в `docs/architecture.md`, раздел 9.

## Коротко

- Адрес API — `https://<адрес BlaBlaTex>/api/v1`, локально — `http://localhost:8000/api/v1`.
- JSON в snake_case, id — UUID, время — ISO 8601 в UTC.
- Схема OpenAPI — [`backend/openapi.json`](https://github.com/Vovaprogrammer/BlaBlaTex/blob/main/backend/openapi.json) в репозитории. Ветка `main` — то, что работает на сайте. Из неё можно сгенерировать клиент (например, `openapi-typescript` или `openapi-python-client`). На самом сайте `/api/docs` и `/api/openapi.json` закрыты.
- Примеры ниже — curl в bash; на Windows подойдёт Git Bash. JSON с русским текстом передавайте файлом (`--data-binary @project.json`): консоль Windows портит кодировку текста прямо в команде.

## Токен

Токен создают на сайте BlaBlaTex, в настройках. Значение показывается один раз — его вставляют в настройку агента или скрипта. Потерянный токен не восстановить: создают новый, старый удаляют на сайте.

- Вид — `bbt_pat_` и 43 буквы и цифры.
- Передаётся заголовком `Authorization: Bearer bbt_pat_...`. Cookie и заголовок `X-CSRF-Protection` не нужны.
- Токен, которым не пользовались 90 дней, отключается сам. Кто работает с агентом, этого не заметит.
- По токену нельзя `/tokens`, `/settings/llm-key`, `/projects/{pid}/export.zip` и `DELETE /account` — ответ `403`. Это делают только на сайте, после входа по паролю: утёкший токен не выпустит себе замену и не удалит аккаунт.
- Правки по токену подписываются в истории проекта автором `mcp`.

Дальше во всех примерах:

```bash
export BBT_URL=http://localhost:8000/api/v1   # установка из готовых образов (docs/install.md) — http://localhost:8765/api/v1
export BBT_TOKEN=bbt_pat_...   # свой токен
AUTH="Authorization: Bearer $BBT_TOKEN"
```

Скрипту без сайта токен можно получить и запросом — войти по паролю и создать токен с cookie:

```bash
curl -s -c cookies.txt -H 'Content-Type: application/json' \
  --data-binary @login.json "$BBT_URL/auth/login"          # {"email": ..., "password": ...}
curl -s -b cookies.txt -H 'X-CSRF-Protection: 1' -H 'Content-Type: application/json' \
  -d '{}' "$BBT_URL/tokens"
```
```json
{"id": "0485ddcd-…", "name": "Токен 2", "created_at": "2026-11-12T08:57:56.785442Z",
 "last_used_at": null, "token": "bbt_pat_…"}
```

## От токена до PDF

В примере ниже весь путь — 16 запросов, из них на сборку — два.

### 1. Профиль

Из профиля берутся ФИО, группа и кафедра для титульного листа.

```bash
curl -s -H "$AUTH" "$BBT_URL/profile"
```
```json
{"last_name": "", "first_name": "", "middle_name": "", "group_name": "", "faculty": "",
 "department": "", "updated_at": "2026-11-12T08:51:39.490240Z"}
```

Пустые поля — спросите у студента и сохраните профиль целиком (`PUT` заменяет все поля):

```bash
curl -s -X PUT -H "$AUTH" -H 'Content-Type: application/json' \
  --data-binary @profile.json "$BBT_URL/profile"
```
`profile.json`:
```json
{"last_name": "Иванов", "first_name": "Иван", "middle_name": "Иванович",
 "group_name": "БИН2401", "faculty": "Информационные технологии",
 "department": "Информатика"}
```

### 2. Шаблон и его поля

```bash
curl -s -H "$AUTH" "$BBT_URL/templates"
```
```json
{"items": [{"slug": "mtuci-lab", "version": 1, "kind": "lab",
            "title": "Лабораторная или практическая работа", "discipline": null}]}
```

Какие поля нужны проекту — в описании шаблона: `required`, тип (`string`, `int`, `text`, `select`) и варианты у `select`.

```bash
curl -s -H "$AUTH" "$BBT_URL/templates/mtuci-lab"
```
```json
{"slug": "mtuci-lab", "…": "…",
 "fields": [{"key": "discipline", "label": "Дисциплина", "type": "string", "required": true, "default": null, "options": []},
            {"key": "lab_number", "label": "Номер работы", "type": "int", "required": true, "default": null, "options": []},
            {"key": "work_type", "label": "Вид работы", "type": "select", "required": false,
             "default": "Лабораторная работа", "options": ["Лабораторная работа", "Практическая работа"]},
            "…"],
 "sections": [{"id": "goal", "title": "Цель работы", "file": "sections/goal.tex", "required": true, "guide": "…"}, "…"]}
```

### 3. Проект

```bash
curl -s -H "$AUTH" -H 'Content-Type: application/json' \
  --data-binary @project.json "$BBT_URL/projects"
```
`project.json`:
```json
{"title": "ЛР 3. Сортировки",
 "template_slug": "mtuci-lab",
 "fields": {"discipline": "Алгоритмы и структуры данных", "lab_number": 3,
            "lab_title": "Сортировки", "variant": "7"}}
```
Ответ — `201`:
```json
{"id": "f15a7e25-702b-449a-adb0-deba9d205223", "title": "ЛР 3. Сортировки", "kind": "lab",
 "template_slug": "mtuci-lab", "template_version": 1,
 "fields": {"discipline": "Алгоритмы и структуры данных", "lab_number": 3, "lab_title": "Сортировки",
            "variant": "7", "work_type": "Лабораторная работа"},
 "main_file": "main.tex", "engine": "xelatex", "…": "…"}
```

Дальше `PID` — id проекта. Уже созданные проекты — `GET /projects`, все одним списком.

### 4. Справка шаблона

То же, что получает ИИ на сайте: что писать в каждом разделе, правила шаблона (`ai_rules`), поля проекта с макросами и макросы класса для кода, скриншотов и таблиц. Дайте её модели перед тем, как писать разделы, — тогда отчёт собирается с первого раза и оформлен как у всех.

```bash
curl -s -H "$AUTH" "$BBT_URL/projects/$PID/template-guide"
```
```json
{"slug": "mtuci-lab", "title": "Лабораторная или практическая работа",
 "discipline": "Алгоритмы и структуры данных", "main_file": "main.tex",
 "sections": [{"id": "goal", "title": "Цель работы", "file": "sections/goal.tex", "required": true,
               "guide": "1–2 предложения: цель из методички или задания, близко к тексту источника. …"}, "…"],
 "ai_rules": "Шаблон один на все дисциплины. Дисциплина — в поле «Дисциплина», …",
 "fields": [{"key": "discipline", "label": "Дисциплина", "value": "Алгоритмы и структуры данных",
             "macro": "\\bbtDiscipline"}, "…"],
 "macros": [{"usage": "\\bbtScreenshot[width]{path}{caption}{label}", "description": "…"},
            {"usage": "\\bbtCodeFile[language]{path}{caption}{label}", "description": "…"}, "…"]}
```

### 5. Материалы

Методичка, задание, код, вывод программы и скриншоты — в папку `materials/`. Одним запросом — до 100 файлов, каждый до 20 МБ. Всё или ничего: если не подошёл хотя бы один файл, не сохраняется ни один, а ошибка называет его. Файл с тем же путём заменяется.

```bash
curl -s -H "$AUTH" -F dir=materials \
  -F files=@zadanie.txt -F files=@sort.py -F files=@output.png \
  "$BBT_URL/projects/$PID/upload"
```
```json
{"items": [{"path": "materials/zadanie.txt", "kind": "text", "role": "material", "mime": "text/plain",
            "size": 283, "version": 7, "updated_at": "…"},
           {"path": "materials/sort.py", "…": "…"},
           {"path": "materials/output.png", "kind": "binary", "role": "material", "mime": "image/png", "…": "…"}]}
```

Типы файлов: `.tex .bib .sty .cls .txt .md .csv`, код (`.py .java .c .cpp .h .js .ts .sql .go .rs .kt .cs`), `.png .jpg .jpeg .svg .pdf .docx .pptx .xlsx`.

### 6. Файлы проекта

Все файлы и папки — одним списком, по пути:

```bash
curl -s -H "$AUTH" "$BBT_URL/projects/$PID/tree"
```
```json
{"items": [{"path": "main.tex", "kind": "text", "role": "source", "mime": "text/plain", "size": 638,
            "version": 1, "updated_at": "2026-11-12T08:52:37.753354Z"},
           {"path": "materials", "kind": "folder", "role": "source", "mime": null, "size": 0, "…": "…"},
           {"path": "meta.tex", "kind": "text", "role": "generated", "mime": "text/plain", "size": 773, "version": 6, "…": "…"},
           {"path": "sections/goal.tex", "kind": "text", "role": "source", "version": 3, "…": "…"}, "…"]}
```

`meta.tex` (`role=generated`) сервер пишет сам из профиля и полей проекта — его не изменить (`403`).

Прочитать файл — текст как есть, версия — в `ETag`:

```bash
curl -s -D - -H "$AUTH" "$BBT_URL/projects/$PID/files/sections/goal.tex"
```
```
HTTP/1.1 200 OK
etag: "3"
content-type: text/plain; charset=utf-8

\section{Цель работы}
% Цель работы из методички или задания — одно-два предложения.
```

Записать файл — текст в теле. Без заголовков файл просто перезаписывается (или создаётся, ответ `201`), папки создаются сами:

```bash
curl -s -X PUT -H "$AUTH" -H 'Content-Type: text/plain; charset=utf-8' \
  --data-binary @progress.tex "$BBT_URL/projects/$PID/files/sections/progress.tex"
```
```json
{"path": "sections/progress.tex", "kind": "text", "role": "source", "mime": "text/plain",
 "size": 494, "version": 91, "updated_at": "2026-11-12T08:59:31.578044Z"}
```

- `If-Match: "<версия>"` — записать, только если файл с тех пор не меняли (так работает правка, см. ниже);
- `If-None-Match: *` — только создать новый: файл уже есть — `409`.

### 7. Сборка

Поставить сборку — `202`, сборка в очереди:

```bash
curl -s -X POST -H "$AUTH" "$BBT_URL/projects/$PID/builds"
```
```json
{"id": "9d24be1e-86f7-4e65-aed9-38c9c8850d41", "project_id": "f15a7e25-…", "status": "queued",
 "engine": "xelatex", "pages": null, "duration_ms": null, "warnings_count": 0, "errors": [],
 "has_pdf": false, "created_at": "2026-11-12T08:53:07.109462Z"}
```

Дальше `BID` — id сборки. Дождаться итога — одним запросом с `wait` (0–60 секунд). Сервер ответит, как только сборка закончится:

```bash
curl -s --max-time 70 -H "$AUTH" "$BBT_URL/builds/$BID?wait=60"
```
```json
{"id": "9d24be1e-…", "status": "ok", "engine": "xelatex", "pages": 3, "duration_ms": 2193,
 "warnings_count": 0, "errors": [], "has_pdf": true, "…": "…"}
```

- Статус всё ещё `queued` или `running` — сборка дольше `wait`: повторите тот же запрос. Сборка, которая идёт дольше 3 минут, получает статус `timeout`.
- Таймаут HTTP-клиента должен быть больше `wait`: у многих библиотек по умолчанию 5–30 секунд.
- Не опрашивайте сборку раз в секунду без `wait`: каждый запрос идёт в лимит токена (120 в минуту).
- Пока сборка в очереди, повторный `POST` возвращает её же — она соберёт и последние правки.
- Файлы не менялись с прошлой успешной сборки — сервер сразу отдаёт её PDF.

Ошибки LaTeX — не ошибка HTTP, а `status: "error"` и список `errors` с файлом, строкой и куском текста вокруг. Покажите модели ошибки (`severity: "error"`) и попросите исправить файл:

```json
{"status": "error", "pages": null, "has_pdf": false, "warnings_count": 4,
 "errors": [{"file": "sections/conclusion.tex", "line": 2,
             "message": "\\begin{itemize} on input line 2 ended by \\end{document}.",
             "context": "  1 | \\section{Выводы}\n> 2 | \\begin{itemize}\n  3 |   \\item Сортировка вставками реализована.",
             "severity": "error"},
            {"file": "sections/progress.tex", "line": 3,
             "message": "Reference `lst:sort' on page 2 undefined", "context": "…", "severity": "warning"}, "…"]}
```

### 8. PDF

```bash
curl -s -H "$AUTH" -o report.pdf "$BBT_URL/builds/$BID/pdf"
```

Имя файла для студента — в `Content-Disposition` (`filename*`, UTF-8), например `ЛР3_Иванов.pdf`. Последняя успешная сборка проекта, если id сборки не сохранили:

```bash
curl -s -H "$AUTH" "$BBT_URL/projects/$PID/builds/latest?status=ok"
```

## Проверки

Готовый отчёт проверяют одним запросом. Какие проверки идут, задаёт шаблон проекта, а их список и тексты — в [`docs/checks.md`](checks.md), часть 1: пустые разделы, заглушки, подписи и ссылки, файлы и сверка с материалами, оформление, сборка.

```bash
curl -s --max-time 70 -X POST -H "$AUTH" "$BBT_URL/projects/$PID/checks?wait=60"
```
```json
{"findings": [
   {"check": "placeholder", "level": "error",
    "message": "В тексте осталась заглушка «TODO». Замените её настоящим текстом или попросите ИИ дописать это место по материалам.",
    "file": "sections/progress.tex", "line": 3, "place": "file", "field": null},
   {"check": "title-empty", "level": "warning",
    "message": "На титульном листе нет группы. Заполните это в профиле — титульник обновится сам.",
    "file": null, "line": null, "place": "profile", "field": "group_name"}],
 "errors_count": 1, "warnings_count": 1, "build_id": "9d24be1e-…", "pdf_checked": true}
```

- `level` — `error`: так отчёт сдавать нельзя; `warning`: нарушено правило оформления или нужно сверить с материалами.
- `file` и `line` — где исправлять, как у ошибок сборки. `place` — `build`: смотрите ошибки сборки `build_id`; `profile` или `fields`: это заполняет студент в профиле или в полях работы (`field` — какое поле), агенту там исправлять нечего.
- Находки в `message` уже сказаны так, чтобы их можно было показать студенту. У тех, что исправляет студент (загрузить материал, сверить число с выводом программы), агент текст не «исправляет» сам — иначе одну выдумку заменит другая.
- Проверки ничего не меняют в проекте и работают, даже пока ИИ сайта занят проектом.

Три проверки читают итог и лог сборки — нужна сборка текущих файлов. Если её нет, проверки сами ставят сборку и ждут её не дольше `wait`:
- обычно хватает одного запроса: после `POST /builds` и `GET /builds/{bid}?wait=60` проверки берут эту же сборку, новую не ставят;
- `pdf_checked: false` — сборка ещё идёт, находок по PDF в ответе нет. Повторите тот же запрос: он найдёт ту же сборку;
- сборка, которую поставили проверки, идёт в лимит сборок (60 за 10 минут); проверка без новой сборки — нет.

## Правка файла

Отдельного запроса «заменить кусок текста» нет: клиент читает файл, меняет текст у себя и записывает с `If-Match`. Так правка не затрёт то, что студент в это время поменял на сайте.

1. `GET /projects/{pid}/files/{path}` — текст и версия из `ETag`.
2. Замена у себя. Кусок не найден или встречается несколько раз — скажите модели, файл не трогайте.
3. `PUT` с `If-Match: "<версия>"`:

```bash
curl -s -X PUT -H "$AUTH" -H 'Content-Type: text/plain; charset=utf-8' -H 'If-Match: "3"' \
  --data-binary @goal.tex "$BBT_URL/projects/$PID/files/sections/goal.tex"
```
```json
{"path": "sections/goal.tex", "kind": "text", "role": "source", "mime": "text/plain",
 "size": 88, "version": 10, "updated_at": "…"}
```

Файл успели изменить — `412`:

```json
{"error": {"code": "file_conflict", "message": "Файл изменён в другом месте",
           "details": {"current_version": 82}}}
```

Прочитайте файл заново и повторите замену на новом тексте — один раз. Куска больше нет — скажите модели, что файл изменился. `current_version: null` и «Файл удалён в другом месте» — файла больше нет.

Ответ `PUT` — новая версия. Если клиент помнит записанный текст и эту версию, следующая правка того же файла обойдётся без чтения — одним `PUT`.

## Списки

Все списки — объект `{"items": [...]}`.

- Целиком, одним запросом: проекты (`GET /projects`, недавно изменённые первыми), файлы проекта (`GET /projects/{pid}/tree`, по пути), шаблоны (`GET /templates`), токены.
- Страницами: история правок (`GET /projects/{pid}/changesets`, новые первыми) и чат (`GET /projects/{pid}/messages`, старые первыми). `limit` — 1–100, по умолчанию 50; `has_more` — есть ли записи старше; следующая страница — `before=<id самой старой из полученных>`: в истории это последняя запись, в чате — первая.

```bash
curl -s -H "$AUTH" "$BBT_URL/projects/$PID/changesets?limit=5"
curl -s -H "$AUTH" "$BBT_URL/projects/$PID/changesets?limit=5&before=<id последней записи>"
```
```json
{"items": [{"id": "963dcb20-…", "author": "user", "message": null, "run_id": null,
            "reverts_id": "…", "reverted_by": null, "created_at": "…", "updated_at": "…"}, "…"],
 "has_more": true}
```

## Ошибки

Все ошибки — в одном виде: `code` — для программы, `message` — на русском, для студента; его можно передавать модели как есть.

```json
{"error": {"code": "not_found", "message": "Проект не найден", "details": {}}}
```

| HTTP, code | Когда | Что делать агенту |
|---|---|---|
| `401 unauthorized` | токен неверный, удалён или отключён после 90 дней без использования | Передать `message` студенту: там сказано, что сделать. Не повторять. |
| `403 forbidden` | запрос только для сайта (`/tokens`, ключ ИИ, архив, удаление аккаунта); `meta.tex` не изменить | Сказать студенту, что это делается на сайте. Не повторять. |
| `404 not_found` | нет проекта, файла или сборки; чужой проект тоже `404` | Перечитать список (`GET /projects`, `GET /tree`) и взять верный id или путь. |
| `409 already_exists` | путь занят: такая папка уже есть, на этом месте папка или над файлом — файл, `If-None-Match: *` на существующий файл | Выбрать другой путь или писать без `If-None-Match`. |
| `412 file_conflict` | файл изменили или удалили после чтения | Перечитать файл и повторить правку — см. «Правка файла». |
| `413 payload_too_large` | текст больше 2 МБ, файл больше 20 МБ, проект станет больше 200 МБ | Сказать студенту; уменьшить файл или убрать лишнее. |
| `415 unsupported_file_type` | тип файла не из списка; текст в путь картинки; содержимое не совпало с расширением | Сменить путь или формат файла (например, скриншот — `.png`). |
| `422 validation_error` | неверный запрос: поле, путь, параметр | Исправить то, что в `details.errors` (`loc` — где, `message` — что). |
| `423 project_locked` | на сайте с этим проектом сейчас работает ИИ | Сказать студенту и повторить позже. Самому прогон не останавливать: его запустил студент. |
| `429 rate_limited` | превышен лимит | Подождать `details.retry_after` секунд (то же — в `Retry-After`) и повторить. |
| `429 quota_exceeded` | кончилась дневная квота ИИ сайта; бывает только у `POST /projects/{pid}/messages` | Сказать студенту, когда квота обновится (`details.resets_at`). Файлы и сборки квоту не тратят. |
| `500 internal` | сбой на сервере | Повторить позже; повторяется — сказать студенту. |

Примеры ответов:

```bash
curl -s -D - -H "Authorization: Bearer bbt_pat_wrong" "$BBT_URL/profile"
```
```
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer

{"error": {"code": "unauthorized", "message": "Токен не подошёл. Проверьте, что он скопирован целиком, или создайте новый в настройках BlaBlaTex", "details": {}}}
```

```bash
curl -s -H "$AUTH" "$BBT_URL/tokens"
```
```json
{"error": {"code": "forbidden", "message": "Это можно сделать только на сайте BlaBlaTex, а не по токену", "details": {}}}
```

```bash
curl -s -H "$AUTH" "$BBT_URL/projects/00000000-0000-0000-0000-000000000000"
```
```json
{"error": {"code": "not_found", "message": "Проект не найден", "details": {}}}
```

```bash
curl -s -H "$AUTH" -H 'Content-Type: application/json' -d '{"path":"sections"}' \
  "$BBT_URL/projects/$PID/folders"
```
```json
{"error": {"code": "already_exists", "message": "Файл или папка с таким путём уже есть", "details": {}}}
```

```bash
curl -s -X PUT -H "$AUTH" --data-binary @big.txt "$BBT_URL/projects/$PID/files/big.txt"   # 3 МБ
```
```json
{"error": {"code": "payload_too_large", "message": "Текстовый файл не может быть больше 2 МБ", "details": {}}}
```

```bash
curl -s -X PUT -H "$AUTH" --data-binary @goal.tex "$BBT_URL/projects/$PID/files/figures/plot.png"
```
```json
{"error": {"code": "unsupported_file_type", "message": "Файл figures/plot.png не сохранить текстом. Подходят: .tex .bib .sty .cls .txt .md .csv .py .java .c .cpp .h .js .ts .sql .go .rs .kt .cs", "details": {}}}
```

```bash
curl -s -X PUT -H "$AUTH" --data-binary @goal.tex "$BBT_URL/projects/$PID/files/sections/50%25.tex"
```
```json
{"error": {"code": "validation_error", "message": "Проверьте введённые данные",
           "details": {"errors": [{"loc": ["path", "path"], "type": "invalid_path",
                                   "message": "Символ % в имени ломает сборку LaTeX — уберите его"}]}}}
```

Запись в проект, пока на сайте работает ИИ:

```json
{"error": {"code": "project_locked", "message": "ИИ сейчас работает с проектом. Дождитесь ответа или остановите его",
           "details": {"run_id": "93c791ca-a52a-4245-bb5c-83057740883d"}}}
```

Сверх лимита запросов:

```
HTTP/1.1 429 Too Many Requests
retry-after: 4

{"error": {"code": "rate_limited", "message": "Слишком много запросов. Повторите через 4 с", "details": {"retry_after": 4}}}
```

Дневная квота ИИ сайта (формат из `docs/architecture.md`, 9.2):

```json
{"error": {"code": "quota_exceeded",
           "message": "Дневной лимит ИИ исчерпан. Он обновится в полночь по Москве. Чтобы продолжить сейчас, добавьте свой ключ в настройках",
           "details": {"resets_at": "2026-11-11T21:00:00Z"}}}
```

## Лимиты

| Что | Лимит |
|---|---|
| Запросы по одному токену | 120 в минуту |
| Сборки студента — с сайта и по токену вместе, и те, что поставили проверки | 60 за 10 минут |
| Текстовый файл | 2 МБ |
| Загружаемый файл | 20 МБ |
| Один запрос загрузки | 100 файлов и 200 МБ |
| Проект | 200 МБ |
| Компиляция | 60 с; сборка, которая идёт дольше 3 минут, получает `timeout` |
| PDF | 50 МБ |

- Окно фиксированное: счётчик обнуляется в начале следующей минуты (у сборок — следующих 10 минут). `retry_after` — сколько секунд до этого.
- Агенту хватает лимита с запасом, если ждать сборку с `wait`, а не опрашивать каждую секунду, и не перечитывать дерево и файлы без нужды.
- Пути файлов — в UTF-8, через `/`, без `..`, `\`, `:`, скрытых имён и спецсимволов TeX (`% # ~ $ & ^ { }`, `"` и обратная кавычка). Полные правила — `docs/architecture.md`, 9.8.
