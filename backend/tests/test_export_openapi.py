import json
from pathlib import Path

import pytest

from app.scripts import export_openapi


@pytest.fixture
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Снапшот во временной папке, чтобы тесты не трогали backend/openapi.json."""
    path = tmp_path / "openapi.json"
    monkeypatch.setattr(export_openapi, "SNAPSHOT", path)
    return path


def test_export_writes_openapi_with_api_paths(snapshot: Path) -> None:
    assert export_openapi.main([]) == 0

    schema = json.loads(snapshot.read_text(encoding="utf-8"))
    assert "/api/v1/projects/{pid}/files/{path}" in schema["paths"]
    assert export_openapi.main(["--check"]) == 0


def test_check_fails_when_snapshot_is_stale(snapshot: Path) -> None:
    export_openapi.write(snapshot)
    text = snapshot.read_text(encoding="utf-8")
    snapshot.write_text(text.replace("/api/v1/auth/login", "/api/v1/auth/signin"), encoding="utf-8")

    assert export_openapi.main(["--check"]) == 1


def test_check_fails_when_snapshot_is_missing(snapshot: Path) -> None:
    assert export_openapi.main(["--check"]) == 1


def test_check_accepts_crlf_line_endings(snapshot: Path) -> None:
    snapshot.write_text(export_openapi.render(), encoding="utf-8", newline="\r\n")

    assert export_openapi.is_fresh(snapshot)
