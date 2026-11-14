"""Подготовка файла SyncTeX и разбор ответов synctex: без Docker, на любой ОС."""

import asyncio
import gzip
import io
import os
import signal
from pathlib import Path
from typing import Any

import pytest

from app import synctex as synctex_module
from app.synctex import (
    Box,
    Source,
    SyncTexFileError,
    SyncTexRunError,
    SyncTexTooLargeError,
    find_boxes,
    find_source,
    parse_output,
    prepare_synctex,
    project_path,
)

# Устроен как настоящий файл сборки mtuci-lab. Титульный лист ушёл в печать на строке
# \bbtTitlePage (main.tex:7), вторая страница — на заголовке следующего раздела
# (тег 6, строка 1): с этой строкой записаны сама страница, номер страницы внизу, строка
# абзаца, который закончился на заголовке, и линейка (r). Слово в строке абзаца — со своей
# строкой (k5,2).
SYNCTEX = """SyncTeX Version:1
Input:1:/tmp/job-abc123/src/./main.tex
Input:2:/opt/blablatex/tex/mtuci-report.cls
Input:3:/usr/local/texlive/2025/texmf-dist/tex/latex/extsizes/size14.clo
Input:4:/tmp/job-abc123/src/out/main.aux
Output:xdv
Magnification:1000
Unit:1
X Offset:4736287
Y Offset:4736287
Content:
!305
{1
[1,7:0,47949085:32557311,47949085,0
(1,7:857753,100953:31699558,1107880,474813
g1,7:857753,100953
)
]
}1
Input:5:/tmp/job-abc123/src/./sections/goal.tex
Input:6:/tmp/job-abc123/src/./разделы/выводы и итоги.tex
!120
{2
[6,1:0,47949085:32557311,47949085,0
(5,1:857753,100953:31699558,1107880,474813
)
r6,1:857753,100953:0,1582693,474813
(6,1:857753,3846335:31699558,617933,203673
k5,2:857753,3846335:2330849
g6,1:20000000,3846335
)
(1,7:857753,5000000:31699558,617933,203673
)
(6,1:857753,47949085:31699558,624845,0
k6,1:16471603,47949085:15613850
)
]
}2
Postamble:
Count:12
Post scriptum:
"""

PREPARED = """SyncTeX Version:1
Input:999999:/blablatex/page
Input:1:main.tex
Input:2:/opt/blablatex/tex/mtuci-report.cls
Input:3:/usr/local/texlive/2025/texmf-dist/tex/latex/extsizes/size14.clo
Input:4:/tmp/job-abc123/src/out/main.aux
Output:xdv
Magnification:1000
Unit:1
X Offset:4736287
Y Offset:4736287
Content:
!305
{1
[999999,7:0,47949085:32557311,47949085,0
(999999,7:857753,100953:31699558,1107880,474813
g999999,7:857753,100953
)
]
}1
Input:5:sections/goal.tex
Input:6:разделы/выводы и итоги.tex
!120
{2
[999999,1:0,47949085:32557311,47949085,0
(5,1:857753,100953:31699558,1107880,474813
)
(999999,1:857753,3846335:31699558,617933,203673
k5,2:857753,3846335:2330849
g999999,1:20000000,3846335
)
(1,7:857753,5000000:31699558,617933,203673
)
(999999,1:857753,47949085:31699558,624845,0
k999999,1:16471603,47949085:15613850
)
]
}2
Postamble:
Count:12
Post scriptum:
"""


def gz(text: str | bytes) -> io.BytesIO:
    data = text.encode() if isinstance(text, str) else text
    return io.BytesIO(gzip.compress(data))


def edit_output(name: str, line: int) -> str:
    return (
        "This is SyncTeX command line utility, version 1.5\n"
        "SyncTeX result begin\n"
        f"Output:output.pdf\nInput:{name}\nLine:{line}\nColumn:-1\nOffset:0\nContext:\n"
        "SyncTeX result end\n"
    )


def view_record(page: int, h: float, v: float, width: float, height: float) -> str:
    return (
        f"Output:output.pdf\nPage:{page}\nx:{h}\ny:{v}\nh:{h}\nv:{v}\nW:{width}\nH:{height}\n"
        "before:\noffset:-1\nmiddle:\nafter:\n"
    )


def view_output(*records: str) -> str:
    return (
        "This is SyncTeX command line utility, version 1.5\nSyncTeX result begin\n"
        + "".join(records)
        + "SyncTeX result end\n"
    )


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("/tmp/job-abc123/src/./main.tex", "main.tex"),
        ("/tmp/job-abc123/src/./sections/goal.tex", "sections/goal.tex"),
        ("/tmp/job-abc123/src/materials/lab.py", "materials/lab.py"),
        ("/tmp/job-zz_9/src/./разделы/цель работы.tex", "разделы/цель работы.tex"),
        # Сборка из кэша: файл SyncTeX от другой сборки, папка другая.
        ("/tmp/job-0000/src/./sections/./goal.tex", "sections/goal.tex"),
        # Папка проекта с такими же именами — путь берётся от первой папки сборки.
        ("/tmp/job-abc/src/./job-1/src/main.tex", "job-1/src/main.tex"),
    ],
)
def test_project_path(name: str, path: str) -> None:
    assert project_path(name) == path


@pytest.mark.parametrize(
    "name",
    [
        "/tmp/job-abc123/src/out/main.aux",
        "/tmp/job-abc123/src/./out/main.aux",
        "/opt/blablatex/tex/mtuci-report.cls",
        "/usr/local/texlive/2025/texmf-dist/tex/latex/base/article.cls",
        "/tmp/job-abc123/src/./a/../b.tex",
        "/tmp/job-abc123/src/./",
        "/tmp/job-abc123/src/a//b.tex",
        "/tmp/synctex-1/src/main.tex",
        "/home/compiler/job-1/src/main.tex",
        "main.tex",
        "./main.tex",
    ],
)
def test_not_project_path(name: str) -> None:
    assert project_path(name) is None


def test_prepare_rewrites_paths_drops_rules_and_detaches_page_line(tmp_path: Path) -> None:
    prepare_synctex(gz(SYNCTEX), tmp_path)

    assert (tmp_path / "output.synctex").read_text(encoding="utf-8") == PREPARED


def test_prepare_keeps_file_without_pages(tmp_path: Path) -> None:
    text = "SyncTeX Version:1\nInput:1:/tmp/job-a/src/./main.tex\nContent:\nPostamble:\n"

    prepare_synctex(gz(text), tmp_path)

    assert (tmp_path / "output.synctex").read_text(encoding="utf-8") == (
        "SyncTeX Version:1\nInput:999999:/blablatex/page\nInput:1:main.tex\nContent:\nPostamble:\n"
    )


@pytest.mark.parametrize(
    "data",
    [
        io.BytesIO(b"not gzip at all"),
        io.BytesIO(gzip.compress(SYNCTEX.encode())[:-20]),
        gz("%PDF-1.7\n"),
        gz(b""),
    ],
    ids=["not-gzip", "truncated", "not-synctex", "empty"],
)
def test_prepare_rejects_broken_file(tmp_path: Path, data: io.BytesIO) -> None:
    with pytest.raises(SyncTexFileError):
        prepare_synctex(data, tmp_path)


def test_prepare_rejects_too_large_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(synctex_module, "MAX_SYNCTEX_BYTES", len(SYNCTEX) - 1)

    with pytest.raises(SyncTexTooLargeError):
        prepare_synctex(gz(SYNCTEX), tmp_path)


def test_prepare_rejects_endless_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(synctex_module, "MAX_LINE_BYTES", 32)

    with pytest.raises(SyncTexFileError):
        prepare_synctex(gz("SyncTeX Version:1\n" + "x" * 100 + "\n"), tmp_path)


def test_parse_output_splits_records() -> None:
    text = view_output(view_record(2, 85.04, 133.57, 481.89, 12.49), view_record(3, 1, 2, 3, 4))

    records = parse_output(text)

    assert [record["Page"] for record in records] == ["2", "3"]
    assert records[0]["H"] == "12.49"


def test_parse_output_without_result() -> None:
    assert parse_output("This is SyncTeX command line utility, version 1.5\n") == []
    assert parse_output(view_output()) == []


def test_find_source_returns_project_file() -> None:
    records = parse_output(edit_output("sections/goal.tex", 2))

    assert find_source(records) == Source(path="sections/goal.tex", line=2)


@pytest.mark.parametrize(
    ("name", "line"),
    [
        # Номер страницы, поля, пустое место, титульный лист — записи страницы со строкой,
        # на которой она ушла в печать (prepare_synctex).
        ("/blablatex/page", 7),
        ("/opt/blablatex/tex/mtuci-report.cls", 120),
        ("/usr/local/texlive/2025/texmf-dist/tex/latex/base/size14.clo", 3),
        ("/tmp/job-abc123/src/out/main.aux", 1),
        # Файл сборки, записанный относительным путём, — тоже не текст студента.
        ("out/main.aux", 1),
        ("sections/goal.tex", 0),
    ],
)
def test_find_source_rejects_text_not_from_student(name: str, line: int) -> None:
    assert find_source(parse_output(edit_output(name, line))) is None


def test_find_source_without_result() -> None:
    assert find_source([]) is None
    assert find_source([{"Input": "main.tex", "Line": "x"}]) is None


def test_find_boxes_converts_baseline_to_top_left() -> None:
    records = parse_output(view_output(view_record(2, 85.039383, 133.567352, 481.889771, 12.4899)))

    boxes = find_boxes(records)

    assert boxes == [Box(page=2, x=85.04, y=121.08, width=481.89, height=12.49)]


def test_find_boxes_clamps_listing_line_to_page() -> None:
    # Строка листинга: synctex отдаёт ящик в две ширины текста, начиная левее страницы.
    records = parse_output(view_output(view_record(2, -396.850372, 470.740143, 963.779541, 13.74)))

    [box] = find_boxes(records)

    assert (box.x, box.width) == (0, 566.93)
    assert (box.y, box.height) == (457.0, 13.74)


def test_find_boxes_skips_duplicates_and_empty_boxes() -> None:
    records = parse_output(
        view_output(
            view_record(3, 85.04, 393.9, 481.89, 24.06),
            view_record(3, 85.04, 393.9, 481.89, 24.06),
            view_record(3, 85.04, 31.79, 481.89, 0),
            view_record(3, 600, 500, -5, 10),
            view_record(2, 85.04, 800.91, 481.89, 9.5),
        )
    )

    boxes = find_boxes(records)

    assert [(box.page, box.y) for box in boxes] == [(3, 369.84), (2, 791.41)]


def test_find_boxes_limits_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(synctex_module, "MAX_BOXES", 2)
    records = parse_output(
        view_output(*(view_record(2, 85, 100 + i * 20, 400, 12) for i in range(5)))
    )

    assert len(find_boxes(records)) == 2


def test_find_boxes_skips_broken_records() -> None:
    records = [{"Page": "2"}, {"Page": "x", "h": "1", "v": "2", "W": "3", "H": "4"}]

    assert find_boxes(records) == []


class FakeRun:
    """Вместо программы synctex: запоминает аргументы и подготовленный файл, отвечает output."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.args: tuple[str, ...] = ()
        self.prepared = ""

    async def __call__(self, workdir: Path, *args: str) -> list[dict[str, str]]:
        self.args = args
        self.prepared = (workdir / "output.synctex").read_text(encoding="utf-8")
        return parse_output(self.output)


async def test_edit_runs_synctex_on_prepared_file(monkeypatch: pytest.MonkeyPatch) -> None:
    run = FakeRun(edit_output("sections/goal.tex", 2))
    monkeypatch.setattr(synctex_module, "run_synctex", run)

    source = await synctex_module.edit(gz(SYNCTEX), 2, 300.0, 128.25)

    assert source == Source(path="sections/goal.tex", line=2)
    assert run.args == ("edit", "-o", "2:300.0000:128.2500:output.pdf")
    assert run.prepared == PREPARED


async def test_edit_hides_page_number(monkeypatch: pytest.MonkeyPatch) -> None:
    # Номер страницы записан со строкой, на которой страница ушла в печать.
    monkeypatch.setattr(synctex_module, "run_synctex", FakeRun(edit_output("/blablatex/page", 1)))

    assert await synctex_module.edit(gz(SYNCTEX), 2, 326.0, 797.0) is None


async def test_view_passes_project_path(monkeypatch: pytest.MonkeyPatch) -> None:
    run = FakeRun(view_output(view_record(2, 85.04, 133.57, 481.89, 12.49)))
    monkeypatch.setattr(synctex_module, "run_synctex", run)

    boxes = await synctex_module.view(gz(SYNCTEX), "разделы/выводы и итоги.tex", 3)

    assert boxes == [Box(page=2, x=85.04, y=121.08, width=481.89, height=12.49)]
    assert run.args == ("view", "-i", "3:0:разделы/выводы и итоги.tex", "-o", "output.pdf")


async def test_workdir_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    run = FakeRun(view_output())
    workdirs: list[Path] = []

    async def remember(workdir: Path, *args: str) -> list[dict[str, str]]:
        workdirs.append(workdir)
        return await run(workdir, *args)

    monkeypatch.setattr(synctex_module, "run_synctex", remember)

    await synctex_module.view(gz(SYNCTEX), "main.tex", 1)
    with pytest.raises(SyncTexFileError):
        await synctex_module.view(io.BytesIO(b"broken"), "main.tex", 1)

    assert len(workdirs) == 1
    assert not workdirs[0].exists()


class FakeProcess:
    pid = 4242

    def __init__(self, exit_code: int | None) -> None:
        self.exit_code = exit_code
        self.killed = False

    async def wait(self) -> int:
        if self.exit_code is None and not self.killed:
            await asyncio.sleep(3600)
        return self.exit_code if self.exit_code is not None else -9


@pytest.fixture
def spawn(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Подменяет запуск процесса: запоминает команду и параметры, процесс сразу выходит с 0.

    Any: параметры create_subprocess_exec разных типов — пути, словари, дескрипторы.
    """
    calls: list[dict[str, Any]] = []

    async def fake_exec(*command: str, **kwargs: Any) -> FakeProcess:
        calls.append({"command": command, **kwargs})
        os.write(kwargs["stdout"], edit_output("main.tex", 9).encode())
        return FakeProcess(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    # На Windows нет групп процессов: здесь проверяем только то, что передаётся в процесс.
    monkeypatch.setattr(os, "killpg", lambda pid, sig: None, raising=False)
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
    return calls


async def test_run_synctex_without_shell_env_and_with_limits(
    tmp_path: Path, spawn: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNCTEX_EDITOR", "touch /tmp/pwned %{input}")
    monkeypatch.setenv("SYNCTEX_VIEWER", "touch /tmp/pwned")

    records = await synctex_module.run_synctex(tmp_path, "edit", "-o", "1:1:1:output.pdf")

    [call] = spawn
    assert call["command"] == (
        "prlimit",
        f"--fsize={synctex_module.MAX_STDOUT_BYTES}",
        "--",
        "synctex",
        "edit",
        "-o",
        "1:1:1:output.pdf",
    )
    assert set(call["env"]) == {"PATH"}
    assert call["cwd"] == tmp_path
    assert call["start_new_session"] is True
    assert records == [
        {
            "Input": "main.tex",
            "Line": "9",
            "Column": "-1",
            "Offset": "0",
            "Context": "",
        }
    ]


async def test_run_synctex_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawn: list[dict[str, Any]]
) -> None:
    async def failing_exec(*command: str, **kwargs: Any) -> FakeProcess:
        return FakeProcess(1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", failing_exec)

    with pytest.raises(SyncTexRunError):
        await synctex_module.run_synctex(tmp_path, "view")


async def test_run_synctex_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawn: list[dict[str, Any]]
) -> None:
    process = FakeProcess(None)

    async def hanging_exec(*command: str, **kwargs: Any) -> FakeProcess:
        return process

    def kill(pid: int, sig: int) -> None:
        process.killed = True

    monkeypatch.setattr(asyncio, "create_subprocess_exec", hanging_exec)
    monkeypatch.setattr(os, "killpg", kill, raising=False)
    monkeypatch.setattr(synctex_module, "SYNCTEX_TIMEOUT_S", 0.05)

    with pytest.raises(SyncTexRunError):
        await synctex_module.run_synctex(tmp_path, "view")
    assert process.killed
