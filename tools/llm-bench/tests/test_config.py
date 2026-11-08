"""Конфигурация провайдеров на синтетических данных."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from llm_bench.config import load_config

KEY = "synthetic-benchmark-key"
PROVIDER = {
    "name": "test",
    "base_url": "https://example.invalid/v1",
    "api_key_env": "BENCH_TEST_KEY",
    "model": "example-model",
    "input_price": "1",
    "output_price": "2",
}


def config_file(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "providers.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_config_loads_prices_and_never_contains_key(tmp_path: Path) -> None:
    provider = load_config(config_file(tmp_path, [PROVIDER]))[0]
    assert provider.input_price == Decimal(1)
    assert provider.output_price == Decimal(2)
    assert KEY not in repr(provider)


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "https://user:secret@example.invalid/v1"},
        {"base_url": "https://example.invalid/v1?key=secret"},
        {"base_url": "http://example.invalid/v1"},
        {"api_key_env": "not-an-env-name"},
        {"api_key": "secret"},
        {"input_price": "-1"},
        {"output_price": None},
    ],
)
def test_config_rejects_invalid_values(tmp_path: Path, changes: dict[str, str | None]) -> None:
    with pytest.raises(ValueError):
        load_config(config_file(tmp_path, [{**PROVIDER, **changes}]))


def test_duplicate_provider_names_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="уникальными"):
        load_config(config_file(tmp_path, [PROVIDER, PROVIDER]))
