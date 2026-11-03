import { useMemo, useState } from 'react';
import { Dialog } from 'radix-ui';
import { unifiedMergeView } from '@codemirror/merge';
import { Button } from '@/components/ui/button';
import type { Draft } from './draft-store';
import { useDraftStore } from './draft-context';
import { SourceEditor } from './source-editor';

export function ConflictDialog({ draft }: { draft: Draft }) {
  const store = useDraftStore();
  const [open, setOpen] = useState(true);
  const diff = useMemo(
    () =>
      unifiedMergeView({
        original: draft.remote?.text ?? '',
        mergeControls: false,
        highlightChanges: true,
        gutter: true,
      }),
    [draft.remote?.text],
  );
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Сравнить версии
      </Button>
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[90svh] w-[calc(100%-2rem)] max-w-4xl -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-auto rounded-2xl border bg-card p-5">
            <Dialog.Title className="text-xl font-semibold">Файл изменился</Dialog.Title>
            <Dialog.Description className="text-sm text-muted-foreground">
              Серверная версия отличается от той, которую вы правили. Ваш текст сохранён в
              черновике. Красным отмечены удалённые строки сервера, зелёным — ваши добавления.
            </Dialog.Description>
            {draft.remote ? (
              <div
                aria-label="Сравнение с серверной версией"
                className="h-80 min-h-40 overflow-auto rounded-xl border"
              >
                <SourceEditor
                  path={draft.path}
                  value={draft.text}
                  readOnly
                  onChange={() => {}}
                  extra={diff}
                />
              </div>
            ) : (
              <p role={draft.error ? 'alert' : 'status'}>
                {draft.error ?? 'Читаем свежую версию файла…'}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-3">
              <Button variant="outline" onClick={() => setOpen(false)}>
                Решить позже
              </Button>
              {!draft.remote && draft.error && (
                <Button onClick={() => store.retry(draft.project, draft.path)}>Повторить</Button>
              )}
              <Button
                variant="outline"
                disabled={!draft.remote}
                className="h-auto min-h-10 whitespace-normal py-2"
                onClick={() => store.resolve(draft.project, draft.path, 'server')}
              >
                Взять версию с сервера
              </Button>
              <Button
                disabled={!draft.remote}
                onClick={() => store.resolve(draft.project, draft.path, 'mine')}
              >
                Оставить мою
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
