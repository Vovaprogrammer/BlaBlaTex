"""Распаковка проекта: только обычные файлы и папки, в пределах лимитов 9.8."""

import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from app import archive
from app.archive import (
    ArchiveError,
    ArchiveTooLargeError,
    extract_project,
    is_safe_relative_path,
    pack_result,
)
from tests.support import make_tar


def tar_with(info: tarfile.TarInfo) -> io.BytesIO:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.addfile(info)
    buffer.seek(0)
    return buffer


@pytest.mark.parametrize(
    "path", ["main.tex", "sections/intro.tex", "materials/рисунок 1.png", "a/b/c/d.tex"]
)
def test_safe_paths(path: str) -> None:
    assert is_safe_relative_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "../x.tex",
        "sections/../../x.tex",
        "./main.tex",
        "a//b.tex",
        "a/./b.tex",
        "sections\\intro.tex",
        "main\x00.tex",
        "line\nbreak.tex",
    ],
)
def test_unsafe_paths(path: str) -> None:
    assert not is_safe_relative_path(path)


def test_extracts_files_and_folders(tmp_path: Path) -> None:
    data = make_tar({"main.tex": "main", "sections/intro.tex": "введение"})

    extract_project(io.BytesIO(data), tmp_path / "src")

    assert (tmp_path / "src" / "main.tex").read_text() == "main"
    assert (tmp_path / "src" / "sections" / "intro.tex").read_text(encoding="utf-8") == "введение"


@pytest.mark.parametrize(
    "member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE]
)
def test_rejects_links_and_special_files(tmp_path: Path, member_type: bytes) -> None:
    info = tarfile.TarInfo("evil.tex")
    info.type = member_type
    info.linkname = "/etc/passwd"

    with pytest.raises(ArchiveError, match="ссылка или особый файл"):
        extract_project(tar_with(info), tmp_path / "src")
    assert not (tmp_path / "src").exists()


@pytest.mark.parametrize("name", ["/etc/cron.d/evil", "../evil.tex", "sub/../../evil.tex"])
def test_rejects_paths_outside_project(tmp_path: Path, name: str) -> None:
    with pytest.raises(ArchiveError, match="Недопустимый путь"):
        extract_project(io.BytesIO(make_tar({name: "x"})), tmp_path / "src")
    assert not (tmp_path / "src").exists()


def test_rejects_not_tar_gz(tmp_path: Path) -> None:
    with pytest.raises(ArchiveError, match=r"tar\.gz"):
        extract_project(io.BytesIO(b"definitely not an archive"), tmp_path / "src")


def test_rejects_truncated_archive(tmp_path: Path) -> None:
    data = make_tar({"main.tex": os.urandom(100_000)})

    with pytest.raises(ArchiveError):
        extract_project(io.BytesIO(data[: len(data) // 2]), tmp_path / "src")


def test_rejects_too_many_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_FILES", 2)

    with pytest.raises(ArchiveTooLargeError):
        extract_project(io.BytesIO(make_tar({"a.tex": "", "b.tex": "", "c.tex": ""})), tmp_path)


def test_rejects_unpacked_size_over_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_UNPACKED_BYTES", 10)

    with pytest.raises(ArchiveTooLargeError):
        extract_project(io.BytesIO(make_tar({"main.tex": "x" * 11})), tmp_path / "src")


def test_pack_result_contains_result_and_existing_files(tmp_path: Path) -> None:
    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    result = {"status": "ok", "exit_code": 0, "duration_ms": 1234}

    data = pack_result(result, {"output.pdf": pdf, "output.synctex.gz": tmp_path / "nope"})

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        assert sorted(tar.getnames()) == ["output.pdf", "result.json"]
        assert json.load(tar.extractfile("result.json")) == result  # type: ignore[arg-type]
        assert tar.extractfile("output.pdf").read() == b"%PDF-1.7"  # type: ignore[union-attr]
