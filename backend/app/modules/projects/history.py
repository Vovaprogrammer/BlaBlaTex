"""История правок проекта (architecture.md 5): changesets, ревизии и сквозные версии файлов.

Сервис файлов начинает каждое изменение с lock_project: строка проекта блокируется до
commit, а изменение получает ProjectChange. Через него сервис:
- сохраняет прежний вид файлов, прежде чем их изменить (snapshot), и отмечает новые (created);
- берёт номер версии для записанного содержимого (next_version);
- копит события file.* и после commit рассылает их с id changeset и автором (publish).

В какой changeset попадает запись, решает Writer: явный changeset прогона ИИ, последний
changeset проекта (склейка автосохранений) или новый.
"""

import asyncio
import difflib
import uuid
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Uuid,
    and_,
    case,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
from app.modules.projects.schemas import (
    FileChange,
    FileDiff,
    FileKind,
    FileRole,
    RevertConflictReason,
)

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
        self._reverts_id: uuid.UUID | None = None
        self._events: list[tuple[EventType, EventData]] = []

    @property
    def written(self) -> bool:
        """Изменение уже что-то записало: у него есть changeset."""
        return self._changeset is not None

    def reverts(self, changeset_id: uuid.UUID) -> None:
        """Изменение — откат changeset: записи пойдут в новый changeset с reverts_id.

        Вызывается до первой записи. Откат не склеивается ни с чем — ни с прежними
        правками, ни со следующими.
        """
        if self._changeset is not None:
            raise RuntimeError("Откат объявляют до первой записи")
        self._reverts_id = changeset_id

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

    def file_changed(self, path: str, version: int) -> None:
        """После commit вкладки узнают, что файл или папка созданы или изменились."""
        data = FileChangedData(
            path=path,
            version=version,
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
        if self._reverts_id is not None:
            return await self._new_changeset()
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
            reverts_id=self._reverts_id,
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


# Что changeset сделал с файлами: вид до (ревизия) и после (следующая ревизия или файл сейчас).


@dataclass(frozen=True)
class FileState:
    """Вид файла или папки в какой-то момент; path = None — файла тогда не было."""

    path: str | None
    kind: FileKind | None
    size: int | None

    @property
    def exists(self) -> bool:
        return self.path is not None


@dataclass(frozen=True)
class Segment:
    """Что changeset сделал с одним файлом или папкой — одна его ревизия.

    after — вид сразу после changeset, current — вид сейчас. Содержимое (вид, текст, blob)
    сравнивает база: тексты до 2 МБ в память не загружаются.
    """

    revision_id: int
    file_id: uuid.UUID
    before: FileState
    after: FileState
    # Ревизия, где лежит вид после changeset; None — вид после — это файл сейчас.
    next_revision_id: int | None
    # Содержимое после changeset то же, что до: файл только перенесён или возвращён как был.
    kept_content: bool
    current: FileState
    current_role: FileRole | None
    current_version: int | None
    # Файл сейчас такой, каким его оставил changeset (current_is_after) или каким он был
    # до changeset (current_is_before); current_has_before_content — то же без пути.
    current_is_after: bool
    current_is_before: bool
    current_has_before_content: bool

    @property
    def is_folder(self) -> bool:
        if self.before.exists:
            return self.before.kind == "folder"
        return "folder" in (self.after.kind, self.current.kind)


_CONTENT = ("kind", "content", "blob_sha256")
# Колонка вида файла по имени: у ревизии, у следующей ревизии или у файла сейчас.
# Any — колонки разных типов: путь, вид, текст, размер.
Column = Callable[[str], ColumnElement[Any]]


def _same(
    left: Column,
    right: Column,
    columns: Sequence[str],
) -> ColumnElement[bool]:
    """Колонки одинаковые у двух видов файла; null равен null (файла нет ни там, ни там)."""
    return and_(*(left(column).is_not_distinct_from(right(column)) for column in columns))


async def segments(session: AsyncSession, changeset_id: uuid.UUID) -> list[Segment]:
    """Ревизии changeset по порядку записи — с видом файла после changeset и сейчас."""
    revision = FileRevision
    following = aliased(FileRevision, name="following")
    later = aliased(FileRevision, name="later")
    next_id = (
        select(func.min(later.id))
        .where(later.file_id == revision.file_id, later.id > revision.id)
        .scalar_subquery()
    )
    has_next = following.id.is_not(None)

    def before(column: str) -> ColumnElement[Any]:
        return getattr(revision, column)

    def next_(column: str) -> ColumnElement[Any]:
        return getattr(following, column)

    def current(column: str) -> ColumnElement[Any]:
        return getattr(File, column)

    def after(column: str) -> ColumnElement[Any]:
        return case((has_next, next_(column)), else_=current(column))

    query = (
        select(
            revision.id,
            revision.file_id,
            revision.path,
            revision.kind,
            revision.size,
            following.id.label("next_id"),
            after("path").label("after_path"),
            after("kind").label("after_kind"),
            after("size").label("after_size"),
            _same(before, after, _CONTENT).label("kept_content"),
            File.path.label("current_path"),
            File.kind.label("current_kind"),
            File.size.label("current_size"),
            File.role.label("current_role"),
            File.version.label("current_version"),
            or_(~has_next, _same(current, next_, ("path", *_CONTENT))).label("current_is_after"),
            _same(current, before, ("path", *_CONTENT)).label("current_is_before"),
            _same(current, before, _CONTENT).label("current_has_before_content"),
        )
        .select_from(revision)
        .outerjoin(following, following.id == next_id)
        .outerjoin(File, File.id == revision.file_id)
        .where(revision.changeset_id == changeset_id)
        .order_by(revision.id)
    )
    return [
        Segment(
            revision_id=row.id,
            file_id=row.file_id,
            before=FileState(row.path, row.kind, row.size),
            after=FileState(row.after_path, row.after_kind, row.after_size),
            next_revision_id=row.next_id,
            kept_content=row.kept_content,
            current=FileState(row.current_path, row.current_kind, row.current_size),
            current_role=row.current_role,
            current_version=row.current_version,
            current_is_after=row.current_is_after,
            current_is_before=row.current_is_before,
            current_has_before_content=row.current_has_before_content,
        )
        for row in await session.execute(query)
    ]


# Diff (architecture.md 9.1): текст больше DIFF_FILE_MAX_BYTES до или после правки и всё,
# что не поместилось в DIFF_MAX_BYTES ответа, — too_large, без diff.
DIFF_FILE_MAX_BYTES = 512 * 1024
DIFF_MAX_BYTES = 2 * 1024 * 1024
_NO_NEWLINE = "\n\\ No newline at end of file\n"


def _lines(text: str) -> list[str]:
    """Строки с \\n на конце, как их делит read_file: только по \\n."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def unified_diff(
    old_path: str | None, new_path: str | None, old: str | None, new: str | None
) -> tuple[str, int, int]:
    """Unified diff двух текстов и сколько строк добавлено и удалено.

    None вместо текста — файла не было (или не стало): в заголовке /dev/null, как у git.
    Последняя строка без перевода строки помечается «\\ No newline at end of file».
    """
    from_file = f"a/{old_path}" if old is not None else "/dev/null"
    to_file = f"b/{new_path}" if new is not None else "/dev/null"
    lines: list[str] = []
    additions = deletions = 0
    diff = difflib.unified_diff(_lines(old or ""), _lines(new or ""), from_file, to_file)
    for index, line in enumerate(diff):
        # Первые две строки — заголовки --- и +++, а не удалённая и добавленная строки.
        if index >= 2 and line.startswith("+"):
            additions += 1
        elif index >= 2 and line.startswith("-"):
            deletions += 1
        lines.append(line if line.endswith("\n") else line + _NO_NEWLINE)
    return "".join(lines), additions, deletions


def _change(segment: Segment) -> FileChange | None:
    """Что changeset сделал с файлом; None — ничего: создал и удалил или вернул как было."""
    before, after = segment.before, segment.after
    if not before.exists:
        return "added" if after.exists else None
    if not after.exists:
        return "deleted"
    if before.path != after.path:
        return "moved"
    return None if segment.kept_content else "modified"


async def _texts(session: AsyncSession, segment: Segment) -> tuple[str | None, str | None]:
    """Текст до и после changeset; None — с этой стороны файла нет."""
    old = None
    if segment.before.kind == "text":
        old = await session.scalar(
            select(FileRevision.content).where(FileRevision.id == segment.revision_id)
        )
    new = None
    if segment.after.kind == "text":
        if segment.next_revision_id is not None:
            new = await session.scalar(
                select(FileRevision.content).where(FileRevision.id == segment.next_revision_id)
            )
        else:
            new = await session.scalar(select(File.content).where(File.id == segment.file_id))
    return old, new


async def changeset_diff(session: AsyncSession, changeset_id: uuid.UUID) -> list[FileDiff]:
    """Что изменил changeset, по пути (architecture.md 9.1).

    Тексты загружаются по одному и только те, что не больше DIFF_FILE_MAX_BYTES; diff
    считается в отдельном потоке — большой файл не задержит другие запросы.
    """
    entries = [
        (segment, change)
        for segment in await segments(session, changeset_id)
        if (change := _change(segment)) is not None
    ]
    # Путь после changeset, у удалённого — до. Порядок по пути: и для ответа, и для того,
    # какие файлы попадут в DIFF_MAX_BYTES.
    entries.sort(key=lambda entry: entry[0].after.path or entry[0].before.path or "")
    budget = DIFF_MAX_BYTES
    result: list[FileDiff] = []
    for segment, change in entries:
        before, after = segment.before, segment.after
        shown = after if after.exists else before
        item = FileDiff(
            path=shown.path or "",
            old_path=before.path if change == "moved" else None,
            change=change,
            kind=shown.kind or "folder",
            diff=None,
            additions=0,
            deletions=0,
            too_large=False,
        )
        kinds = {before.kind, after.kind} - {None}
        if kinds != {"text"} or (change == "moved" and segment.kept_content):
            # Картинки, документы, папки, смена вида и перенос без правки — без diff.
            result.append(item)
            continue
        sizes = [state.size or 0 for state in (before, after)]
        if max(sizes) > DIFF_FILE_MAX_BYTES or budget <= 0:
            result.append(item.model_copy(update={"too_large": True}))
            continue
        old, new = await _texts(session, segment)
        text, additions, deletions = await asyncio.to_thread(
            unified_diff, before.path, after.path, old, new
        )
        size = len(text.encode())
        if size > budget:
            result.append(item.model_copy(update={"too_large": True}))
            continue
        budget -= size
        result.append(
            item.model_copy(update={"diff": text, "additions": additions, "deletions": deletions})
        )
    return result


# Откат (architecture.md 9.1): план — что вернуть и что мешает. Применяет его сервис файлов.


@dataclass
class RevertPlan:
    """Что откат вернёт к виду до changeset и что ему мешает.

    files — файлы (не папки), которые нужно вернуть к before; folders — папки changeset,
    которые ещё не такие, как до него. Папки откатываются мягко: созданная удаляется,
    если пуста, удалённая или перенесённая — создаётся на прежнем месте.
    """

    files: list[Segment]
    folders: list[Segment]
    conflicts: list[tuple[str, RevertConflictReason]]

    @property
    def empty(self) -> bool:
        return not (self.files or self.folders or self.conflicts)


def plan_revert(changeset_segments: Sequence[Segment]) -> RevertPlan:
    """План отката по ревизиям changeset; пути, занятые другими файлами, проверяет сервис.

    Файл, который уже такой, как до changeset, пропускается. Файл, который после changeset
    менял кто-то ещё (у него несколько ревизий в changeset или он сейчас не такой, каким
    changeset его оставил), — конфликт changed.
    """
    by_file: dict[uuid.UUID, list[Segment]] = {}
    for segment in changeset_segments:
        by_file.setdefault(segment.file_id, []).append(segment)
    plan = RevertPlan(files=[], folders=[], conflicts=[])
    for file_segments in by_file.values():
        first, last = file_segments[0], file_segments[-1]
        if first.current_is_before:
            continue
        if first.is_folder:
            plan.folders.append(first)
        elif len(file_segments) > 1 or not first.current_is_after:
            shown = first.current.path or last.after.path or first.before.path or ""
            plan.conflicts.append((shown, "changed"))
        else:
            plan.files.append(first)
    return plan
