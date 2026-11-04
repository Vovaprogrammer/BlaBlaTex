"""История правок проекта (architecture.md 5): changesets, ревизии и сквозные версии файлов.

Сервис файлов начинает каждое изменение с lock_project: строка проекта блокируется до
commit, а изменение получает ProjectChange. Через него сервис:
- сохраняет прежний вид файлов, прежде чем их изменить (snapshot), и отмечает новые (created);
- берёт номер версии для записанного содержимого (next_version);
- копит события file.* и после commit рассылает их с id changeset и автором (publish).

В какой changeset попадает запись, решает Writer: явный changeset прогона ИИ, последний
changeset проекта (склейка автосохранений) или новый.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, Uuid, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import (
    Author,
    EventData,
    EventPublisher,
    EventType,
    FileChangedData,
    FileDeletedData,
    FileMovedData,
)
from app.modules.projects.models import Changeset, File, FileRevision, Project

# Склейка автосохранений (раздел 5): запись студента попадает в changeset, начатый меньше
# этого назад. Считается от первой правки, а не от последней: иначе час работы без перерыва
# стал бы одним changeset, и откат стёр бы весь час.
COALESCE_WINDOW = timedelta(minutes=10)
# Чьи записи склеиваются: студента через сайт и через MCP. ИИ пишет в changeset прогона,
# meta.tex и шаблон — каждый раз в новый.
COALESCED_AUTHORS: frozenset[Author] = frozenset({"user", "mcp"})


@dataclass(frozen=True)
class Writer:
    """Кто и в рамках чего меняет файлы: журнал событий, автор и changeset (раздел 5).

    user_id — от чьего имени запись; None — не от имени пользователя. changeset_id —
    явный changeset, например прогона ИИ (ToolContext.changeset_id); None — сервис
    выберет сам: продолжит последний changeset проекта (склейка) или начнёт новый.
    """

    events: EventPublisher
    author: Author
    user_id: uuid.UUID | None
    changeset_id: uuid.UUID | None = None


class _Silent:
    """Журнал, который ничего не пишет: проект из шаблона создаётся без событий —
    его ещё никто не смотрит."""

    async def publish(self, project_id: uuid.UUID, type_: EventType, data: EventData) -> None:
        return None


SILENT = _Silent()


class ProjectChange:
    """Одно изменение файлов проекта под блокировкой его строки — до commit.

    Changeset выбирается при первой записи, а не заранее: изменение, которое ничего
    не записало, не оставит в истории пустой changeset.
    """

    def __init__(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        writer: Writer,
        *,
        last_version: int,
        last_changeset_id: uuid.UUID | None,
    ) -> None:
        self.session = session
        self.project_id = project_id
        self.writer = writer
        self._version = last_version
        self._last_changeset_id = last_changeset_id
        self._changeset: Changeset | None = None
        self._events: list[tuple[EventType, EventData]] = []

    def next_version(self) -> int:
        """Номер версии для нового содержимого файла: сквозной в пределах проекта."""
        self._version += 1
        return self._version

    async def changeset(self) -> Changeset:
        """Changeset, в который идут записи этого изменения."""
        if self._changeset is None:
            self._changeset = await self._choose_changeset()
        return self._changeset

    async def snapshot(self, condition: ColumnElement[bool]) -> None:
        """Сохраняет прежний вид файлов и папок проекта, подходящих под condition.

        Вызывается до того, как файлы изменятся: запрос сначала сбрасывает в базу
        несохранённые изменения сессии, и они попали бы в «прежний» вид. Текст
        копируется в базе, в память он не загружается. У файла, чья последняя ревизия
        уже в этом changeset, новой ревизии нет: его вид до changeset уже сохранён.
        """
        changeset = await self.changeset()
        latest = (
            select(FileRevision.changeset_id)
            .where(FileRevision.file_id == File.id)
            .order_by(FileRevision.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = select(
            literal(changeset.id, Uuid),
            File.id,
            File.path,
            File.kind,
            File.content,
            File.blob_sha256,
            File.mime,
            File.size,
        ).where(
            File.project_id == self.project_id,
            condition,
            latest.is_distinct_from(changeset.id),
        )
        columns = ["changeset_id", "file_id", "path", "kind", "content", "blob_sha256"]
        await self.session.execute(
            insert(FileRevision).from_select([*columns, "mime", "size"], rows)
        )

    async def created(self, file_ids: Collection[uuid.UUID]) -> None:
        """Отмечает новые файлы и папки: до changeset их не было."""
        if not file_ids:
            return
        changeset = await self.changeset()
        await self.session.execute(
            insert(FileRevision).values(
                [{"changeset_id": changeset.id, "file_id": file_id} for file_id in file_ids]
            )
        )

    def file_changed(self, file: File) -> None:
        """После commit вкладки узнают, что файл или папка созданы или изменились."""
        data = FileChangedData(
            path=file.path,
            version=file.version,
            changeset_id=self._written_changeset_id(),
            author=self.writer.author,
        )
        self._events.append((EventType.FILE_CHANGED, data))

    def file_moved(self, from_path: str, to_path: str) -> None:
        data = FileMovedData(from_=from_path, to=to_path, changeset_id=self._written_changeset_id())
        self._events.append((EventType.FILE_MOVED, data))

    def file_deleted(self, path: str) -> None:
        data = FileDeletedData(path=path, changeset_id=self._written_changeset_id())
        self._events.append((EventType.FILE_DELETED, data))

    async def save(self) -> None:
        """Записывает в строку проекта счётчик версий и changeset последней записи.

        Не коммитит. updated_at проекта не трогает: поднимать ли проект в списке,
        решил lock_project.
        """
        if self._changeset is None:
            return
        self._changeset.updated_at = datetime.now(UTC)
        await self.session.execute(
            update(Project)
            .where(Project.id == self.project_id)
            .values(
                last_file_version=self._version,
                last_changeset_id=self._changeset.id,
                updated_at=Project.updated_at,
            )
        )

    async def publish(self) -> None:
        """Рассылает накопленные события. Только после commit."""
        for type_, data in self._events:
            await self.writer.events.publish(self.project_id, type_, data)
        self._events.clear()

    def _written_changeset_id(self) -> uuid.UUID:
        # Событие — о записи, а записи без changeset не бывает: сначала snapshot или created.
        if self._changeset is None:
            raise RuntimeError("Событие о файле до записи ревизии")
        return self._changeset.id

    async def _choose_changeset(self) -> Changeset:
        if self.writer.changeset_id is not None:
            changeset = await self.session.get(Changeset, self.writer.changeset_id)
            if changeset is None or changeset.project_id != self.project_id:
                raise ValueError(f"Changeset {self.writer.changeset_id} не из этого проекта")
            return changeset
        if self.writer.author in COALESCED_AUTHORS and self._last_changeset_id is not None:
            last = await self.session.get(Changeset, self._last_changeset_id)
            if last is not None and self._continues(last):
                return last
        return await self._new_changeset()

    def _continues(self, last: Changeset) -> bool:
        """Запись продолжает последний changeset проекта: тот же автор от имени того же
        пользователя, не откат и начат меньше COALESCE_WINDOW назад.

        Последний changeset — это changeset последней записи в проект. Поэтому запись
        другого автора (ИИ, meta.tex) и откат прерывают склейку, а вкладки одного
        студента пишут в один changeset.
        """
        return (
            last.author == self.writer.author
            and last.author_user_id == self.writer.user_id
            and last.reverts_id is None
            and datetime.now(UTC) - last.created_at < COALESCE_WINDOW
        )

    async def _new_changeset(self) -> Changeset:
        changeset = Changeset(
            project_id=self.project_id,
            author=self.writer.author,
            author_user_id=self.writer.user_id,
        )
        self.session.add(changeset)
        await self.session.flush()
        return changeset


async def lock_project(
    session: AsyncSession, project_id: uuid.UUID, writer: Writer, *, touch: bool = True
) -> ProjectChange | None:
    """Начало изменения файлов: блокирует строку проекта до commit.

    Изменения файлов одного проекта идут по очереди: проверка версии, «путь свободен»,
    счётчик версий и выбор changeset не пересекутся с другим запросом. touch — поднять
    проект в списке: правка файла тоже его изменение. Пересоздание meta.tex проект
    не поднимает — сам пользователь его не менял. Проекта нет — None.
    Порядок блокировок тот же, что у удаления проекта: сначала проект, потом файлы.
    """
    if touch:
        statement = (
            update(Project)
            .where(Project.id == project_id)
            .values(updated_at=datetime.now(UTC))
            .returning(Project.last_file_version, Project.last_changeset_id)
        )
    else:
        statement = (
            select(Project.last_file_version, Project.last_changeset_id)
            .where(Project.id == project_id)
            .with_for_update()
        )
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        return None
    return ProjectChange(
        session,
        project_id,
        writer,
        last_version=row.last_file_version,
        last_changeset_id=row.last_changeset_id,
    )
