import { useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { sessionKey } from '@/features/auth/use-session';
import { workspaceKeys } from '@/features/workspace/workspace-queries';
import { DraftStore } from './draft-store';
import { DraftContext } from './draft-context';

export function DraftProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const owner = useSyncExternalStore(
    (listener) => client.getQueryCache().subscribe(listener),
    () =>
      client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id ?? '',
    () => '',
  );
  const [stores] = useState(() => new Map<string, DraftStore>());
  const save = useMutation({
    meta: { editorSave: true },
    mutationFn: async (input: {
      owner: string;
      project: string;
      path: string;
      text: string;
      etag: string;
      signal: AbortSignal;
    }) => {
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        input.owner
      )
        throw new DOMException('Сессия изменилась', 'AbortError');
      const { data, response } = await api.PUT('/api/v1/projects/{pid}/files/{path}', {
        params: { path: { pid: input.project, path: input.path } },
        body: input.text,
        headers: { 'Content-Type': 'text/plain; charset=utf-8', 'If-Match': input.etag },
        signal: input.signal,
      });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил сохранение файла.');
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id ===
        input.owner
      )
        client.setQueryData<components['schemas']['FileTree']>(
          workspaceKeys.tree(input.project),
          (previous) =>
            previous
              ? { items: previous.items.map((item) => (item.path === input.path ? data : item)) }
              : previous,
        );
      return response.headers.get('ETag') ?? `"${data.version}"`;
    },
  });
  const mutate = save.mutateAsync;
  const store = useMemo(() => {
    let value = stores.get(owner);
    if (!value) {
      value = new DraftStore({
        load: async (project, path, signal) => {
          await client.cancelQueries({
            queryKey: [...workspaceKeys.file(project, path), 'editor'],
            exact: true,
          });
          if (signal.aborted) throw new DOMException('Загрузка отменена', 'AbortError');
          return client.fetchQuery({
            queryKey: [...workspaceKeys.file(project, path), 'editor'],
            staleTime: 0,
            queryFn: async ({ signal: querySignal }) => {
              const { data, response } = await api.GET('/api/v1/projects/{pid}/files/{path}', {
                params: { path: { pid: project, path } },
                parseAs: 'text',
                signal: AbortSignal.any([signal, querySignal]),
              });
              const etag = response.headers.get('ETag');
              if (!etag || !/^"\d+"$/.test(etag))
                throw new ApiError(
                  0,
                  'invalid_response',
                  'Сервер не прислал версию файла. Повторите загрузку.',
                );
              return { text: data ?? '', etag };
            },
          });
        },
        save: (project, path, text, etag, signal) =>
          mutate({ owner, project, path, text, etag, signal }),
      });
      stores.set(owner, value);
    }
    return value;
  }, [client, owner, mutate, stores]);
  useEffect(() => {
    if (owner) store.resume();
    return () => store.pause();
  }, [owner, store]);
  useEffect(() => {
    const listener = (event: BeforeUnloadEvent) => {
      if (store.pending().length) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', listener);
    return () => window.removeEventListener('beforeunload', listener);
  }, [store]);
  return <DraftContext.Provider value={store}>{children}</DraftContext.Provider>;
}
