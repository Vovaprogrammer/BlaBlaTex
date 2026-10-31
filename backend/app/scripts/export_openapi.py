"""Снапшот контракта API (architecture.md 9.1): пишет backend/openapi.json или проверяет его.

uv run python -m app.scripts.export_openapi           # обновить файл
uv run python -m app.scripts.export_openapi --check   # только проверить, так делает CI
"""

import argparse
import json
import sys
from pathlib import Path

import structlog

from app.core.config import BACKEND_DIR
from app.main import create_app

SNAPSHOT = BACKEND_DIR / "openapi.json"

logger = structlog.get_logger(__name__)


def render() -> str:
    """OpenAPI приложения — ровно в том виде, в каком файл лежит в репозитории."""
    return json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n"


def is_fresh(path: Path) -> bool:
    # read_text превращает \r\n в \n: на Windows git может выдать файл с CRLF.
    return path.exists() and path.read_text(encoding="utf-8") == render()


def write(path: Path) -> None:
    path.write_text(render(), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Снапшот OpenAPI для фронта")
    parser.add_argument(
        "--check", action="store_true", help="не писать файл, а проверить, что он свежий"
    )
    args = parser.parse_args(argv)

    if not args.check:
        write(SNAPSHOT)
        logger.info("openapi_snapshot_written", path=str(SNAPSHOT))
        return 0
    if is_fresh(SNAPSHOT):
        return 0
    logger.error(
        "openapi_snapshot_stale",
        path=str(SNAPSHOT),
        fix="uv run python -m app.scripts.export_openapi и закоммить openapi.json",
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
