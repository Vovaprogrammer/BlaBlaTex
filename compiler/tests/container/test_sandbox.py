"""Песочница: контейнер запущен с флагами из docker-compose.yml, и сборка в нём работает."""

import json
import re
from typing import Any

import pytest

from tests.support import COMPOSE_ENV, DEV_COMPOSE, REPO_DIR, Compiler, docker

pytestmark = pytest.mark.container

# Any: вывод docker inspect и docker compose config — произвольный JSON.
Json = dict[str, Any]

# Класс из фикстуры лежит в /opt/blablatex/tex — туда в dev монтируется templates/_shared.
CLASS_DOC = r"""
\documentclass{bbt-test}
\begin{document}
Отчёт о лабораторной работе. Ёж, щука, ЪЬ.
\begin{lstlisting}[language=Python]
print("Привет")  # комментарий
\end{lstlisting}
\end{document}
"""


@pytest.fixture(scope="module")
def container(compiler: Compiler) -> Json:
    """docker inspect работающего контейнера компилятора."""
    return json.loads(docker("inspect", compiler.container).stdout)[0]


@pytest.fixture(scope="module")
def dev_config() -> Json:
    """docker-compose.yml так, как его видит docker compose, — без тестовых подмен."""
    result = docker(
        "compose",
        "--project-directory",
        str(REPO_DIR),
        "--file",
        str(DEV_COMPOSE),
        "config",
        "--format",
        "json",
        env=COMPOSE_ENV,
    )
    return json.loads(result.stdout)


def test_root_filesystem_is_read_only(container: Json) -> None:
    assert container["HostConfig"]["ReadonlyRootfs"] is True


def test_runs_as_non_root_user(container: Json) -> None:
    assert container["Config"]["User"] == "compiler"


def test_resource_limits_are_set(container: Json) -> None:
    host = container["HostConfig"]

    assert host["Memory"] > 0
    assert host["NanoCpus"] > 0
    assert host["PidsLimit"] > 0


def test_no_capabilities_and_no_privilege_escalation(container: Json) -> None:
    host = container["HostConfig"]

    assert host["CapDrop"] == ["ALL"]
    assert "no-new-privileges:true" in host["SecurityOpt"]
    assert host["Init"] is True


def test_only_internal_network(container: Json) -> None:
    [network] = container["NetworkSettings"]["Networks"]

    assert json.loads(docker("network", "inspect", network).stdout)[0]["Internal"] is True


def test_no_secrets_in_environment(container: Json) -> None:
    names = {item.split("=", 1)[0] for item in container["Config"]["Env"]}

    # compose тестов знает POSTGRES_PASSWORD — в контейнер он попасть не должен.
    assert not [name for name in names if re.search("PASSWORD|SECRET|TOKEN|KEY|POSTGRES", name)]


def test_only_tmpfs_is_writable(compiler: Compiler) -> None:
    script = "touch /tmp/probe /home/compiler/probe && ! touch /opt/probe 2>/dev/null && echo OK"

    output = docker("exec", compiler.container, "sh", "-c", script).stdout.decode()

    assert output.strip() == "OK"


def test_fonts_and_shared_class_work_on_read_only_root(compiler: Compiler) -> None:
    build = compiler.compile({"main.tex": CLASS_DOC})

    assert build.result["status"] == "ok", build.log
    assert "/opt/blablatex/tex/bbt-test.cls" in build.log
    assert "TU/LiberationSerif(0)" in build.log
    assert "Missing character" not in build.log


def test_dev_compose_keeps_compiler_offline(dev_config: Json) -> None:
    compiler = dev_config["services"]["compiler"]
    proxy = dev_config["services"]["compiler-proxy"]

    assert "ports" not in compiler
    assert "environment" not in compiler
    assert list(compiler["networks"]) == ["compiler"]
    assert dev_config["networks"]["compiler"]["internal"] is True
    # Наружу — только прокси и только на localhost.
    assert [port["host_ip"] for port in proxy["ports"]] == ["127.0.0.1"]
