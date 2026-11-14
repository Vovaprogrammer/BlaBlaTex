"""Конфигурация бенчмарка без значений ключей."""

import ipaddress
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key_env: str
    model: str
    input_price: Decimal | None = None
    output_price: Decimal | None = None


def _price(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Цена должна быть неотрицательным числом") from error
    if not price.is_finite() or price < 0:
        raise ValueError("Цена должна быть неотрицательным числом")
    return price


def load_config(path: Path) -> list[Provider]:
    """Читает список провайдеров; ключи задаются только именами переменных окружения."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Не удалось прочитать конфигурацию провайдеров") from error
    if not isinstance(data, list) or not data:
        raise ValueError("Конфигурация должна быть непустым списком провайдеров")
    providers = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("Провайдер должен быть объектом")
        allowed = {"name", "base_url", "api_key_env", "model", "input_price", "output_price"}
        if set(entry) - allowed:
            raise ValueError("В конфигурации провайдера есть неизвестные поля")
        for field in ("name", "base_url", "api_key_env", "model"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"Не задано поле {field}")
        url = urlsplit(entry["base_url"])
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise ValueError("base_url должен быть HTTP(S) URL без ключей, запроса и фрагмента")
        if url.scheme == "http":
            try:
                loopback = ipaddress.ip_address(url.hostname).is_loopback
            except ValueError:
                loopback = url.hostname == "localhost"
            if not loopback:
                raise ValueError("HTTP разрешён только для локального сервера")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry["api_key_env"]):
            raise ValueError("api_key_env должен содержать имя переменной окружения")
        input_price = _price(entry.get("input_price"))
        output_price = _price(entry.get("output_price"))
        if (input_price is None) != (output_price is None):
            raise ValueError("Для расчёта стоимости нужны обе цены")
        providers.append(
            Provider(
                name=entry["name"],
                base_url=entry["base_url"].rstrip("/"),
                api_key_env=entry["api_key_env"],
                model=entry["model"],
                input_price=input_price,
                output_price=output_price,
            )
        )
    if len({provider.name for provider in providers}) != len(providers):
        raise ValueError("Имена провайдеров должны быть уникальными")
    return providers
