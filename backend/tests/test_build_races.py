"""Гонки воркеров вокруг очереди сборок — на настоящих отдельных соединениях.

Обычные тесты идут в одной транзакции с откатом, а в одном соединении гонку не увидеть.
Здесь «воркеры» — параллельные run_project_builds со своим пулом соединений к тестовой
базе (фикстура live, tests/live_builds.py).
"""

import asyncio
from dataclasses import dataclass, field

import httpx
import pytest

from app.modules.builds.compiler import CompilerClient
from app.modules.builds.models import Build
from app.modules.builds.service import run_project_builds, wait_for_build
from app.modules.projects import service as projects_service
from tests.fake_compiler import FakeCompiler, parse_compile_request
from tests.fake_events import FakeEvents
from tests.helpers import writer
from tests.live_builds import MAIN_TEX, Live, builds_of, new_project, queue

# Тест падает, а не висит, если сборка так и не дошла до компилятора.
WAIT_S = 5


@dataclass
class GatedCompiler:
    """Компилятор, который держит сборки, пока тест их не отпустит, и считает, сколько
    сборок каждого проекта идёт одновременно (проект — по тексту main.tex в архиве)."""

    fake: FakeCompiler = field(default_factory=FakeCompiler)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    running: dict[bytes, int] = field(default_factory=dict)
    peak: dict[bytes, int] = field(default_factory=dict)
    total: int = 0
    peak_total: int = 0
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    def __post_init__(self) -> None:
        self.fake.respond = self.respond

    def client(self) -> CompilerClient:
        return self.fake.client()

    async def respond(self, request: httpx.Request) -> httpx.Response:
        project = parse_compile_request(request).files()["main.tex"]
        async with self.changed:
            self.running[project] = self.running.get(project, 0) + 1
            self.peak[project] = max(self.peak.get(project, 0), self.running[project])
            self.total += 1
            self.peak_total = max(self.peak_total, self.total)
            self.changed.notify_all()
        await self.release.wait()
        async with self.changed:
            self.running[project] -= 1
            self.total -= 1
        return self.fake.build_response()

    async def wait_compiling(self, count: int) -> None:
        """Ждёт, пока у компилятора одновременно окажется count сборок."""
        async with asyncio.timeout(WAIT_S), self.changed:
            await self.changed.wait_for(lambda: self.total >= count)


def worker(live: Live, compiler: GatedCompiler, build: Build) -> asyncio.Task[None]:
    return asyncio.create_task(
        run_project_builds(
            live.sessionmaker, live.storage, compiler.client(), FakeEvents(), build.id
        )
    )


async def test_builds_of_one_project_never_run_in_parallel(live: Live) -> None:
    compiler = GatedCompiler()
    project_id = await new_project(live)
    first = await queue(live, project_id)
    first_worker = worker(live, compiler, first)
    await compiler.wait_compiling(1)

    # Пока первая собирается, студент правит файл и дважды нажимает «Собрать».
    async with live.sessionmaker() as session:
        await projects_service.write_text_file(session, writer(), project_id, "intro.tex", "Правка")
    second = await queue(live, project_id)
    again = await queue(live, project_id)
    # Второй воркер получил задание на вторую сборку, но начать её не может.
    await asyncio.wait_for(worker(live, compiler, second), WAIT_S)
    waiting = await builds_of(live, project_id)
    compiler.release.set()
    await asyncio.wait_for(first_worker, WAIT_S)

    assert again.id == second.id != first.id
    assert [build.status for build in waiting] == ["running", "queued"]
    assert len(compiler.fake.requests) == 2
    assert compiler.peak[MAIN_TEX.encode()] == 1
    # Вторую сборку взял воркер первой, когда закончил её.
    finished = await builds_of(live, project_id)
    assert [(build.id, build.status) for build in finished] == [
        (first.id, "ok"),
        (second.id, "ok"),
    ]


async def test_same_build_taken_by_several_workers_runs_once(live: Live) -> None:
    compiler = GatedCompiler()
    compiler.release.set()
    build = await queue(live, await new_project(live))

    # Задание пришло трижды: повтор после сбоя и проверка потерянных сборок.
    await asyncio.wait_for(
        asyncio.gather(*(worker(live, compiler, build) for _ in range(3))), WAIT_S
    )

    assert len(compiler.fake.requests) == 1
    [stored] = await builds_of(live, build.project_id)
    assert stored.status == "ok"


async def test_builds_of_different_projects_run_in_parallel(live: Live) -> None:
    compiler = GatedCompiler()
    first = await queue(live, await new_project(live, MAIN_TEX))
    second = await queue(live, await new_project(live, MAIN_TEX + "%\n"))

    workers = [worker(live, compiler, first), worker(live, compiler, second)]
    await compiler.wait_compiling(2)
    compiler.release.set()
    await asyncio.wait_for(asyncio.gather(*workers), WAIT_S)

    assert compiler.peak_total == 2


async def test_parallel_requests_queue_one_build(live: Live) -> None:
    project_id = await new_project(live)

    builds = await asyncio.gather(*(queue(live, project_id) for _ in range(5)))

    assert len({build.id for build in builds}) == 1
    assert [build.status for build in await builds_of(live, project_id)] == ["queued"]


# Ожидание итога для compile() у ИИ-агента (B2.5).


async def test_wait_for_build_returns_result_when_finished(live: Live) -> None:
    compiler = GatedCompiler()
    build = await queue(live, await new_project(live))
    building = worker(live, compiler, build)
    waiting = asyncio.create_task(wait_for_build(live.sessionmaker, build.id, poll_s=0.01))
    await compiler.wait_compiling(1)
    await asyncio.sleep(0.05)
    assert not waiting.done()

    compiler.release.set()
    result = await asyncio.wait_for(waiting, WAIT_S)
    await building

    assert result is not None
    assert (result.id, result.status) == (build.id, "ok")


async def test_wait_for_build_is_limited_by_caller(live: Live) -> None:
    # Воркера нет: сборка так и стоит в очереди.
    build = await queue(live, await new_project(live))

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            await wait_for_build(live.sessionmaker, build.id, poll_s=0.01)


async def test_wait_for_build_of_deleted_project(live: Live) -> None:
    build = await queue(live, await new_project(live))
    async with live.sessionmaker() as session:
        project = await projects_service.get_project(session, build.project_id)
        assert project is not None
        await projects_service.delete_project(session, project)

    assert await wait_for_build(live.sessionmaker, build.id, poll_s=0.01) is None
