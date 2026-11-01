"""Версия окружения для кэша сборок бэкенда: без Docker, на любой ОС."""

from pathlib import Path

import pytest

from app.version import compiler_version, shared_fingerprint


def write(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def test_version_joins_image_version_and_shared_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COMPILER_VERSION", "2025.1")
    write(tmp_path, {"mtuci-report.cls": "% класс"})

    assert compiler_version(tmp_path) == f"2025.1+{shared_fingerprint(tmp_path)}"


def test_version_outside_image_is_dev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("COMPILER_VERSION", raising=False)

    assert compiler_version(tmp_path).startswith("dev+")


def test_fingerprint_is_stable_for_same_files(tmp_path: Path) -> None:
    files = {"mtuci-report.cls": "% класс", "img/logo.svg": "<svg/>"}

    first = shared_fingerprint(write(tmp_path / "a", files))
    second = shared_fingerprint(write(tmp_path / "b", files))

    assert first == second
    assert len(first) == 16


@pytest.mark.parametrize(
    "changed",
    [
        {"mtuci-report.cls": "% класс, исправленный"},
        {"mtuci-report.cls": "% класс", "extra.sty": ""},
        {"renamed.cls": "% класс"},
    ],
    ids=["content", "new-file", "renamed"],
)
def test_fingerprint_follows_shared_class_changes(tmp_path: Path, changed: dict[str, str]) -> None:
    before = shared_fingerprint(write(tmp_path / "a", {"mtuci-report.cls": "% класс"}))

    assert shared_fingerprint(write(tmp_path / "b", changed)) != before


def test_fingerprint_of_missing_dir_is_fingerprint_of_empty_dir(tmp_path: Path) -> None:
    assert shared_fingerprint(tmp_path / "missing") == shared_fingerprint(tmp_path)
