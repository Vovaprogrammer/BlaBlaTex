import { useMemo, useState } from 'react';
import { Dialog } from 'radix-ui';
import { unifiedMergeView } from '@codemirror/merge';
import type { components } from '@/api/schema';
import { Button } from '@/components/ui/button';
import { SourceEditor } from '@/features/editor/source-editor';
import { parseDiff, type DiffHunk } from './parse-diff';

type File = components['schemas']['FileDiff'];
const labels: Record<File['change'], string> = {
  added: 'Добавлен',
  modified: 'Изменён',
  deleted: 'Удалён',
  moved: 'Перенесён',
};

export function ChangesetDialog({
  files,
  onClose,
  restoreFocus,
}: {
  files: File[];
  onClose: () => void;
  restoreFocus: () => void;
}) {
  const [selected, setSelected] = useState(0);
  const file = files[selected] ?? files[0];
  if (!file) return null;
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <Dialog.Content
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            restoreFocus();
          }}
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[90svh] w-[calc(100%-2rem)] max-w-4xl -translate-x-1/2 -translate-y-1/2 flex-col gap-3 overflow-auto rounded-2xl border bg-card p-4 sm:p-5"
        >
          <Dialog.Title className="text-xl font-semibold">Правки агента</Dialog.Title>
          <Dialog.Description className="text-sm text-muted-foreground">
            Зелёным выделены добавления, красным — удаления. Показаны изменённые участки и соседние
            строки.
          </Dialog.Description>
          <label className="grid gap-1 text-sm">
            Файл
            <select
              className="w-full min-w-0 truncate rounded-lg border bg-secondary p-2"
              value={selected}
              onChange={(event) => setSelected(Number(event.currentTarget.value))}
            >
              {files.map((entry, index) => (
                <option key={index} value={index}>
                  {labels[entry.change]} · {entry.path}
                </option>
              ))}
            </select>
          </label>
          {file.old_path && <p className="break-all text-sm">Прежний путь: {file.old_path}</p>}
          <FileComparison key={selected} file={file} />
          <div className="flex flex-wrap justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="outline">Закрыть</Button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function FileComparison({ file }: { file: File }) {
  if (file.too_large) return <p className="text-sm">Этот файл слишком большой для сравнения.</p>;
  if (!file.diff) return <p className="text-sm">Для этого изменения нет текстового сравнения.</p>;
  return <TextComparison path={file.path} diff={file.diff} />;
}

function TextComparison({ path, diff }: { path: string; diff: string }) {
  const hunks = useMemo(() => parseDiff(diff), [diff]);
  const [index, setIndex] = useState(0);
  const hunk = hunks[index];
  if (!hunk) return <p className="text-sm">В этом файле нет изменённых строк.</p>;
  return (
    <div
      className="min-h-24 space-y-3 overflow-auto"
      aria-label="Сравнение версий файла"
      role="region"
    >
      {hunks.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Button
            size="sm"
            variant="outline"
            disabled={index === 0}
            onClick={() => setIndex(index - 1)}
          >
            Назад
          </Button>
          <span>
            Фрагмент {index + 1} из {hunks.length}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={index + 1 === hunks.length}
            onClick={() => setIndex(index + 1)}
          >
            Дальше
          </Button>
        </div>
      )}
      <Hunk key={index} path={path} hunk={hunk} />
    </div>
  );
}

function Hunk({ path, hunk }: { path: string; hunk: DiffHunk }) {
  const merge = useMemo(
    () =>
      unifiedMergeView({
        original: hunk.before,
        mergeControls: false,
        gutter: true,
      }),
    [hunk.before],
  );
  return (
    <section className="overflow-hidden rounded-xl border">
      <p className="border-b bg-secondary px-3 py-2 text-xs text-muted-foreground">
        Начало фрагмента — до: {hunk.oldLine}, после: {hunk.newLine}
      </p>
      <div className="h-48">
        <SourceEditor path={path} value={hunk.after} readOnly onChange={() => {}} extra={merge} />
      </div>
    </section>
  );
}
