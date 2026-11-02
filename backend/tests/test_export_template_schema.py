import json
from pathlib import Path

import pytest

from app.scripts import export_template_schema


@pytest.fixture
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Схема во временной папке, чтобы тесты не трогали templates/_schema/."""
    path = tmp_path / "_schema" / "template.schema.json"
    monkeypatch.setattr(export_template_schema, "SNAPSHOT", path)
    return path


def test_export_writes_manifest_schema(snapshot: Path) -> None:
    assert export_template_schema.main([]) == 0

    schema = json.loads(snapshot.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "template.yaml"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["slug", "version", "kind", "title", "engine", "main"]
    field = schema["$defs"]["ManifestField"]["properties"]
    assert field["key"]["pattern"] == "^[a-z]+(_[a-z]+)*$"
    assert field["type"]["enum"] == ["string", "int", "text", "select"]
    assert "ai_rules" in schema["properties"]
    assert export_template_schema.main(["--check"]) == 0


def test_check_fails_when_schema_is_stale(snapshot: Path) -> None:
    export_template_schema.write(snapshot)
    text = snapshot.read_text(encoding="utf-8")
    snapshot.write_text(text.replace('"ai_rules"', '"rules"'), encoding="utf-8")

    assert export_template_schema.main(["--check"]) == 1


def test_check_fails_when_schema_is_missing(snapshot: Path) -> None:
    assert export_template_schema.main(["--check"]) == 1


def test_check_accepts_crlf_line_endings(snapshot: Path) -> None:
    snapshot.parent.mkdir()
    snapshot.write_text(export_template_schema.render(), encoding="utf-8", newline="\r\n")

    assert export_template_schema.is_fresh(snapshot)
