"""Воркер сборок для тестов API: POST /builds только ставит сборку в очередь (9.1), а
BuildWorker.run() собирает поставленное — как воркер, но в сессии теста."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import Storage
from app.modules.builds.compiler import CompilerClient
from app.modules.builds.service import run_queued_build
from tests.fake_compiler import FakeCompiler
from tests.fake_events import FakeEvents


@dataclass
class BuildWorker:
    session: AsyncSession
    storage: Storage
    fake: FakeCompiler = field(default_factory=FakeCompiler)
    # Свой клиент вместо подменного — например, к настоящему компилятору.
    compiler: CompilerClient | None = None
    # Сборки, которые API отправил воркеру, по порядку.
    queued: list[uuid.UUID] = field(default_factory=list)
    # События сборок, которые отправил воркер.
    events: FakeEvents = field(default_factory=FakeEvents)

    async def enqueue(self, build_id: uuid.UUID) -> None:
        self.queued.append(build_id)

    async def run(self) -> None:
        """Собирает всё, что отправили воркеру."""
        compiler = self.compiler or self.fake.client()
        while self.queued:
            await run_queued_build(
                self.session, self.storage, compiler, self.events, self.queued.pop(0)
            )
