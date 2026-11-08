# Проверки A0.1 — конфигурация бенчмарка

Из `tools/llm-bench/`, Python 3.12 и uv 0.13.6:

```sh
uv sync --locked
uv run --locked ruff check llm_bench/config.py tests/test_config.py
uv run --locked ruff format --check llm_bench/config.py tests/test_config.py
uv run --locked pytest tests/test_config.py
```

Проверки используют только синтетическую конфигурацию; запросы к LLM не выполняются.
08.11.2026: Ruff и форматирование прошли, 9 тестов прошли.
