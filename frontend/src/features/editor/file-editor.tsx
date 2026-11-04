import { useEffect, useState, useSyncExternalStore } from 'react';
import { LockKeyhole } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useDraftStore } from './draft-context';
import { SourceEditor } from './source-editor';
import { ConflictDialog } from './conflict-dialog';
import type { EditorTarget } from './editor-navigation';

const statuses = {
  loading: 'Загружаем файл…',
  saved: 'Все изменения сохранены',
  dirty: 'Есть несохранённые изменения',
  saving: 'Сохраняем…',
  error: 'Изменения не сохранены',
  conflict: 'Файл изменился на сервере',
  locked: 'Редактирование временно недоступно',
  missing: 'Файл недоступен. Ваш текст остался в черновике',
};
export function FileEditor({
  id,
  path,
  readOnly = false,
  version,
  target,
}: {
  id: string;
  path: string;
  readOnly?: boolean;
  version?: number;
  target?: EditorTarget;
}) {
  const store = useDraftStore();
  const draft = useSyncExternalStore(store.subscribe, () => store.get(id, path));
  const [copyMessage, setCopyMessage] = useState('');
  useEffect(() => {
    store.open(id, path, readOnly);
  }, [store, id, path, readOnly]);
  useEffect(() => {
    if (version !== undefined) store.open(id, path, readOnly, version);
  }, [store, id, path, readOnly, version]);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b p-3">
        <p className="break-words text-sm font-semibold">{path}</p>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {readOnly ? (
            <span className="flex items-center gap-2">
              <LockKeyhole className="size-4" aria-hidden="true" />
              Создаётся автоматически, только чтение
            </span>
          ) : (
            <span role="status">{draft ? statuses[draft.status] : 'Загружаем файл…'}</span>
          )}
          {draft && ['error', 'locked', 'missing'].includes(draft.status) && (
            <Button size="sm" variant="outline" onClick={() => store.retry(id, path)}>
              Повторить
            </Button>
          )}
          {draft?.backup !== undefined && (
            <Button size="sm" variant="outline" onClick={() => store.restore(id, path)}>
              Вернуть мой черновик
            </Button>
          )}
          {draft?.status === 'conflict' && <ConflictDialog draft={draft} />}
        </div>
        {draft?.error && (
          <p role="alert" className="text-sm text-destructive">
            {draft.error}
          </p>
        )}
        {draft &&
          ['error', 'locked', 'missing', 'conflict'].includes(draft.status) &&
          draft.etag && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard
                  ?.writeText(draft.text)
                  .then(() => setCopyMessage('Текст скопирован'))
                  .catch(() =>
                    setCopyMessage(
                      'Не удалось скопировать. Выделите текст в редакторе и скопируйте вручную.',
                    ),
                  );
              }}
            >
              Скопировать мой текст
            </Button>
          )}
        {copyMessage && (
          <p role="status" className="text-sm">
            {copyMessage}
          </p>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {!draft || (draft.status === 'loading' && !draft.etag) ? (
          <p role="status" className="p-4">
            Загружаем файл…
          </p>
        ) : (
          <SourceEditor
            target={target}
            path={path}
            value={draft.text}
            readOnly={
              readOnly ||
              ['loading', 'locked', 'missing', 'conflict'].includes(draft.status) ||
              !draft.etag
            }
            onChange={(text) => store.edit(id, path, text)}
          />
        )}
      </div>
    </div>
  );
}
