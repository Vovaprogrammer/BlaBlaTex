"""check-template без TeX: разбор лога и проверка папки шаблона."""

from pathlib import Path

import pytest

from app.check_template import find_errors, main

LOG = r"""This is XeTeX, Version 3.141592653-2.6-0.999997 (TeX Live 2025)
(./main.tex
LaTeX2e <2025-11-01>
./main.tex:5: Undefined control sequence.
l.5 \bbtNoSuchMacro
! Emergency stop.
Output written on out/main.xdv (1 page, 2304 bytes).
"""


def test_find_errors_keeps_file_line_and_bang_lines() -> None:
    assert find_errors(LOG) == ["./main.tex:5: Undefined control sequence.", "! Emergency stop."]


def test_find_errors_with_spaces_in_file_name() -> None:
    line = "./sections/ход работы.tex:3: Undefined control sequence."

    assert find_errors(f"(./main.tex\n{line}\n") == [line]


def test_template_must_not_have_out_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("main.tex", "meta.sample.tex", "out/main.pdf"):
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text("")

    assert main([str(tmp_path)]) == 1
    assert "папка out/" in capsys.readouterr().out


def test_missing_template_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "nope")]) == 1
    assert "нет папки шаблона" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["main.tex", "meta.sample.tex"])
def test_template_needs_main_and_sample_meta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    for name in {"main.tex", "meta.sample.tex"} - {missing}:
        (tmp_path / name).write_text("")

    assert main([str(tmp_path)]) == 1
    assert f"нет файла {missing}" in capsys.readouterr().out
