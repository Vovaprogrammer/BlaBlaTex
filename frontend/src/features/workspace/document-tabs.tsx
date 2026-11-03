import { useEffect, useRef } from 'react';
import { FileText, LockKeyhole, X } from 'lucide-react';
import { useIsMutating, useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import { PdfPlaceholder } from './workspace-placeholders';
import { fileName, type ProjectFile } from './file-tree-data';
import { useProjectTree, workspaceKeys } from './workspace-queries';
import type { TabAction, WorkspaceTabs } from './workspace-tabs';

function tabId(path: string | null) {
  return path === null ? 'document-pdf-tab' : `document-file-${encodeURIComponent(path)}`;
}
export function DocumentTabs({
  id,
  state,
  dispatch,
}: {
  id: string;
  state: WorkspaceTabs;
  dispatch: (action: TabAction) => void;
}) {
  const tree = useProjectTree(id);
  const changing = useIsMutating({ mutationKey: ['projects', id, 'files'] });
  const tabs = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (tree.data && !changing && !tree.isFetching && !tree.isStale)
      dispatch({
        kind: 'prune',
        paths: tree.data.items.filter((item) => item.kind !== 'folder').map((item) => item.path),
      });
  }, [tree.data, tree.isFetching, tree.isStale, dispatch, changing]);
  const selected =
    state.active === null ? undefined : tree.data?.items.find((item) => item.path === state.active);
  function close(path: string) {
    dispatch({ kind: 'close', path });
    window.setTimeout(
      () => tabs.current?.querySelector<HTMLButtonElement>('[aria-selected=true]')?.focus(),
      0,
    );
  }
  return (
    <section aria-label="Документ и файлы" className="flex h-full min-h-0 flex-col">
      <div
        ref={tabs}
        role="tablist"
        aria-label="Открытые документы"
        className="flex min-h-14 shrink-0 overflow-x-auto border-b px-2"
        onKeyDown={(event) => {
          if (!(event.target instanceof HTMLElement) || event.target.getAttribute('role') !== 'tab')
            return;
          const paths = [null, ...state.paths];
          const index = paths.indexOf(state.active);
          let next: number;
          if (event.key === 'ArrowRight') next = (index + 1) % paths.length;
          else if (event.key === 'ArrowLeft') next = (index - 1 + paths.length) % paths.length;
          else if (event.key === 'Home') next = 0;
          else if (event.key === 'End') next = paths.length - 1;
          else if (event.key === 'Delete' && state.active !== null) {
            event.preventDefault();
            close(state.active);
            return;
          } else return;
          event.preventDefault();
          const path = paths[next] ?? null;
          dispatch({ kind: 'select', path });
          document.getElementById(tabId(path))?.focus();
        }}
      >
        {[null, ...state.paths].map((path) => (
          <div
            key={path ?? '__pdf'}
            className={`flex shrink-0 items-center gap-1 border-b-2 ${state.active === path ? 'border-ring bg-secondary' : 'border-transparent'}`}
          >
            <button
              type="button"
              role="tab"
              id={tabId(path)}
              aria-selected={state.active === path}
              aria-controls="document-panel"
              tabIndex={state.active === path ? 0 : -1}
              onClick={() => dispatch({ kind: 'select', path })}
              className="flex min-h-12 max-w-52 items-center gap-2 rounded px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              title={path ?? 'Предпросмотр PDF'}
            >
              <FileText className="size-4 shrink-0 text-ring" aria-hidden="true" />
              <span className="truncate">{path === null ? 'PDF' : fileName(path)}</span>
            </button>
            {path !== null && (
              <button
                type="button"
                aria-label={`Закрыть ${path}`}
                onClick={() => close(path)}
                className="mr-1 flex size-7 items-center justify-center rounded outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-3" aria-hidden="true" />
              </button>
            )}
          </div>
        ))}
      </div>
      <div
        role="tabpanel"
        id="document-panel"
        aria-labelledby={tabId(state.active)}
        className="min-h-0 flex-1 overflow-hidden"
      >
        {state.active === null ? (
          <PdfPlaceholder />
        ) : selected ? (
          <FilePreview key={selected.path} id={id} file={selected} />
        ) : (
          <p role="status" className="p-4">
            Обновляем сведения о файле…
          </p>
        )}
      </div>
    </section>
  );
}

function FilePreview({ id, file }: { id: string; file: ProjectFile }) {
  const text = useQuery({
    queryKey: workspaceKeys.file(id, file.path),
    enabled: file.kind === 'text',
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/projects/{pid}/files/{path}', {
        params: { path: { pid: id, path: file.path } },
        parseAs: 'text',
        signal,
      });
      return data ?? '';
    },
  });
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b p-4">
        <p className="break-words text-sm font-semibold">{file.path}</p>
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          {file.role === 'generated' ? (
            <>
              <LockKeyhole className="size-4 shrink-0" aria-hidden="true" />
              Создаётся автоматически, только чтение
            </>
          ) : (
            'Просмотр файла. Редактирование скоро станет доступно.'
          )}
        </p>
      </div>
      {file.kind !== 'text' ? (
        <p className="p-5 text-sm text-muted-foreground">
          Просмотр этого типа файла скоро станет доступен.
        </p>
      ) : text.isPending ? (
        <p role="status" className="p-4">
          Загружаем файл…
        </p>
      ) : text.isError ? (
        <div role="alert" className="space-y-4 p-4">
          <p>{errorMessage(text.error)}</p>
          <Button onClick={() => void text.refetch()}>Повторить</Button>
        </div>
      ) : (
        <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-sm leading-6">
          {text.data || 'Файл пуст'}
        </pre>
      )}
    </div>
  );
}
