# Запуск eval-кейсов

Раннер использует публичный API локальной установки BlaBlaTex. Поддерживаются только
`localhost` и loopback: настоящие материалы и токен не отправляются внешним сервисам.
Нужны работающие API, воркер, Redis, PostgreSQL, компилятор и персональный API-токен.
Модель API должна быть настроена для локальной работы. Токен и настройки в репозиторий
не добавляются; файлы `.env` раннер не читает.

Запуск из корня репозитория после установки backend-зависимостей:

```sh
uv run --project backend python -m eval.runner --data-dir "$EVAL_DATA_DIR" \
  --output-dir /путь/вне/репозитория/eval-results --url http://127.0.0.1:8765/api/v1
```

`BLABLATEX_TOKEN` берётся из окружения. `--timeout` задаёт срок ожидания прогона и
отдельно сборки в секундах (по умолчанию 300). Каждый каталог с `case.yaml` и
`materials/` создаёт новый проект; материалы загружаются с сохранением подкаталогов.
Недопустимые сервером форматы не пропускаются: кейс получит ошибку. Каталог результатов
должен быть вне набора данных; JSON и PDF создаются с правами 0600 и не перезаписываются.
Проекты на сервере автоматически не удаляются.

Результат каждого кейса — JSON со `schema_version: 1`: `case_id`, `project_id`,
`run_id`, `run_status`, `build_id`, `build_status`, `pdf_downloaded`, `tokens_in`,
`tokens_out`, `cost`, `compile_calls`, `section_files`, `error`. Идентификаторы,
статусы и токены могут быть `null`, если соответствующий этап или событие недоступны.
`cost` и `compile_calls` пока всегда `null`: публичный API не даёт достоверную стоимость
отдельного прогона и полноту истории вызовов. `section_files` — отображение названия
раздела из кейса в `true`/`false`/`null` по guide и дереву файлов. Наличие файла не
подтверждает его заполненность или присутствие раздела в PDF. `error` — безопасный код
без текста сервера и содержимого материалов; ошибка одного кейса не прекращает остальные.
При ошибке или неуспешной сборке процесс возвращает ненулевой код.

Проверки без сети и настоящих материалов из корня репозитория:

```sh
uv run --project backend ruff check --config backend/pyproject.toml eval/runner.py eval/tests/test_runner.py
uv run --project backend ruff format --check --config backend/pyproject.toml eval/runner.py eval/tests/test_runner.py
uv run --project backend python -m pytest -q eval/tests/test_runner.py
```
