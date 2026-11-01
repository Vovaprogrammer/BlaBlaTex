"""Атаки из задачи B1.4 против настоящего контейнера: каждая должна провалиться.

Документы пишут в лог метки BBT-...: по ним видно, что атакующий код действительно
выполнялся и упёрся в защиту, а не сломался раньше.
"""

import io
import tarfile

import pytest

from tests.support import SIMPLE_DOC, Compiler, make_tar, wait_until

pytestmark = pytest.mark.container

ENGINES = ["xelatex", "pdflatex"]


def read_attack(path: str) -> str:
    """Документ читает файл двумя способами: \\openin и \\input."""
    return rf"""
\documentclass{{article}}
\newread\attack
\begin{{document}}
\openin\attack={path}
\ifeof\attack
  \typeout{{BBT-READ-BLOCKED}}
\else
  \readline\attack to\stolen
  \typeout{{BBT-READ-LEAK:\stolen}}
\fi
\input{{{path}}}
\end{{document}}
"""


def write_attack(path: str) -> str:
    return rf"""
\documentclass{{article}}
\newwrite\attack
\begin{{document}}
\typeout{{BBT-WRITE-START}}
\immediate\openout\attack={path}
\immediate\write\attack{{pwned}}
\immediate\closeout\attack
\typeout{{BBT-WRITE-DONE}}
\end{{document}}
"""


SHELL_ESCAPE_DOC = r"""
\documentclass{article}
\newread\pipe
\begin{document}
\immediate\write18{touch immediate.txt}
Page.\write18{touch delayed.txt}
\newpage
\openin\pipe="|touch piped.txt"
\IfFileExists{immediate.txt}{\typeout{BBT-SHELL-LEAK}}{\typeout{BBT-IMMEDIATE-BLOCKED}}
\IfFileExists{delayed.txt}{\typeout{BBT-SHELL-LEAK}}{\typeout{BBT-DELAYED-BLOCKED}}
\IfFileExists{piped.txt}{\typeout{BBT-SHELL-LEAK}}{\typeout{BBT-PIPE-BLOCKED}}
\end{document}
"""

# Если latexmk прочитает rc-файл, сборка упадёт, а в /tmp контейнера появится файл.
LATEXMKRC = 'system("touch /tmp/latexmkrc-pwned"); die "BBT: latexmkrc executed\\n";\n'

ENDLESS_LOOP_DOC = r"""
\documentclass{article}
\begin{document}
\def\x{\x}\x
\end{document}
"""

# Бесконечный вывод в лог: остановит таймаут или лимит на размер файла.
LOG_FLOOD_DOC = r"""
\documentclass{article}
\begin{document}
\loop\message{flood flood flood flood flood flood flood flood}\iftrue\repeat
\end{document}
"""

NETWORK_PROBE = """
import socket
for target in (("1.1.1.1", 443), ("8.8.8.8", 53), ("example.com", 80)):
    try:
        socket.create_connection(target, timeout=3).close()
        print("CONNECTED", target)
    except OSError:
        print("BLOCKED", target)
try:
    socket.getaddrinfo("example.com", 443)
    print("DNS-RESOLVED")
except OSError:
    print("DNS-BLOCKED")
"""


BUILD_PROCESSES = ("latexmk", "xelatex", "pdflatex")


def assert_no_build_processes(compiler: Compiler) -> None:
    wait_until(
        lambda: not any(name in compiler.processes() for name in BUILD_PROCESSES),
        timeout=10,
        message="В контейнере остались процессы сборки",
    )


def test_harness_reads_allowed_file(compiler: Compiler) -> None:
    """Контроль: файл из проекта читается, значит, метки ниже честно показывают блокировку."""
    build = compiler.compile({"main.tex": read_attack("allowed.txt"), "allowed.txt": "hello"})

    assert "BBT-READ-LEAK:hello" in build.log


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../x",
        # Достаточно «..», чтобы из любой рабочей папки дойти до корня: файл точно существует.
        "../../../../../../../../etc/passwd",
        "/proc/self/environ",
    ],
)
def test_reading_outside_project_is_blocked(compiler: Compiler, engine: str, path: str) -> None:
    build = compiler.compile({"main.tex": read_attack(path)}, engine=engine)

    assert "BBT-READ-BLOCKED" in build.log
    assert "BBT-READ-LEAK" not in build.log
    assert "root:x:0:0" not in build.log
    assert "PATH=" not in build.log
    assert build.result["status"] == "error"


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("path", ["/tmp/bbt-pwned.tex", "../bbt-pwned.tex"])
def test_writing_outside_project_is_blocked(compiler: Compiler, engine: str, path: str) -> None:
    build = compiler.compile({"main.tex": write_attack(path)}, engine=engine)

    assert "BBT-WRITE-START" in build.log
    assert "BBT-WRITE-DONE" not in build.log
    assert f"I can't write on file `{path}'" in build.log
    assert not compiler.path_exists("/tmp/bbt-pwned.tex")


@pytest.mark.parametrize("engine", ENGINES)
def test_shell_escape_is_disabled(compiler: Compiler, engine: str) -> None:
    build = compiler.compile({"main.tex": SHELL_ESCAPE_DOC}, engine=engine)

    assert build.result["status"] == "ok"
    for marker in ("BBT-IMMEDIATE-BLOCKED", "BBT-DELAYED-BLOCKED", "BBT-PIPE-BLOCKED"):
        assert marker in build.log
    assert "BBT-SHELL-LEAK" not in build.log
    assert "runsystem(touch immediate.txt)...disabled" in build.log


def test_latexmkrc_is_not_executed(compiler: Compiler) -> None:
    files = {"main.tex": SIMPLE_DOC, ".latexmkrc": LATEXMKRC, "latexmkrc": LATEXMKRC}

    build = compiler.compile(files)

    assert build.result["status"] == "ok"
    assert build.files["output.pdf"].startswith(b"%PDF")
    assert not compiler.path_exists("/tmp/latexmkrc-pwned")


def test_endless_loop_is_stopped_by_timeout(compiler: Compiler) -> None:
    build = compiler.compile({"main.tex": ENDLESS_LOOP_DOC}, timeout_s=3)

    assert build.result["status"] == "timeout"
    assert build.result["exit_code"] is None
    assert 3000 <= build.result["duration_ms"] < 10_000
    assert "output.pdf" not in build.files
    # Убит не только latexmk, но и запущенный им xelatex.
    assert_no_build_processes(compiler)


def test_log_flood_is_stopped(compiler: Compiler) -> None:
    build = compiler.compile({"main.tex": LOG_FLOOD_DOC}, timeout_s=10)

    assert build.result["status"] in ("timeout", "error")
    assert len(build.files["output.log"]) <= 64 * 1024 * 1024
    assert_no_build_processes(compiler)


def test_container_has_no_network(compiler: Compiler) -> None:
    output = compiler.exec("python", "-c", NETWORK_PROBE)

    assert output.count("BLOCKED") == 4
    assert "CONNECTED" not in output
    assert "DNS-RESOLVED" not in output


def symlink_archive() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        link = tarfile.TarInfo("main.tex")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "archive",
    [
        # TeX открыл бы ссылку как обычный файл проекта, и openin_any бы не помог.
        symlink_archive(),
        make_tar({"main.tex": SIMPLE_DOC, "../evil.tex": "x"}),
        make_tar({"main.tex": SIMPLE_DOC, "/tmp/evil.tex": "x"}),
    ],
    ids=["symlink", "parent-dir", "absolute-path"],
)
def test_unsafe_archive_is_rejected(compiler: Compiler, archive: bytes) -> None:
    response = compiler.post_archive(archive)

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["type"] == "invalid_archive"
    assert not compiler.path_exists("/tmp/evil.tex")


@pytest.mark.parametrize(
    "main",
    [
        # latexmk выполнил бы Perl-код из опции -e.
        "-e system('touch /tmp/pwned');.tex",
        # latexmk передаёт имя в shell в двойных кавычках: обратная кавычка там выполняется.
        "x`touch /tmp/pwned`.tex",
        "x$(touch /tmp/pwned).tex",
    ],
    ids=["latexmk-option", "backtick", "dollar"],
)
def test_main_name_cannot_inject_commands(compiler: Compiler, main: str) -> None:
    response = compiler.post({main: SIMPLE_DOC}, main=main)

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["type"] == "invalid_main"
    assert not compiler.path_exists("/tmp/pwned")


def test_stale_outputs_in_archive_are_rejected(compiler: Compiler) -> None:
    # Иначе latexmk мог бы счесть сборку свежей и отдать подложенный PDF как результат.
    response = compiler.post({"main.tex": SIMPLE_DOC, "out/main.pdf": b"%PDF-forged"})

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["type"] == "reserved_path"
