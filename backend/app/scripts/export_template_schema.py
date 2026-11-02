"""JSON Schema для template.yaml (architecture.md 9.5): пишет файл схемы или проверяет его.

По схеме редактор подсказывает авторам шаблонов поля манифеста, а CI шаблонов проверяет
template.yaml. Источник правды — модель TemplateManifest.

uv run python -m app.scripts.export_template_schema           # обновить файл
uv run python -m app.scripts.export_template_schema --check   # только проверить, так делает CI
"""

import argparse
import json
import sys
from pathlib import Path

import structlog

from app.core.config import TEMPLATES_DIR
from app.modules.templates.manifest import TemplateManifest

SNAPSHOT = TEMPLATES_DIR / "_schema" / "template.schema.json"
DRAFT = "https://json-schema.org/draft/2020-12/schema"

logger = structlog.get_logger(__name__)


def render() -> str:
    """Схема манифеста — ровно в том виде, в каком файл лежит в репозитории."""
    schema = {"$schema": DRAFT, **TemplateManifest.model_json_schema()}
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def is_fresh(path: Path) -> bool:
    # read_text превращает \r\n в \n: на Windows git может выдать файл с CRLF.
    return path.exists() and path.read_text(encoding="utf-8") == render()


def write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JSON Schema для template.yaml")
    parser.add_argument(
        "--check", action="store_true", help="не писать файл, а проверить, что он свежий"
    )
    args = parser.parse_args(argv)

    if not args.check:
        write(SNAPSHOT)
        logger.info("template_schema_written", path=str(SNAPSHOT))
        return 0
    if is_fresh(SNAPSHOT):
        return 0
    logger.error(
        "template_schema_stale",
        path=str(SNAPSHOT),
        fix="uv run python -m app.scripts.export_template_schema и закоммить схему",
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
