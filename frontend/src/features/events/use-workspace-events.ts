import { useState } from 'react';
import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import type { components } from '@/api/schema';
import type { EventConnection } from '@/api/project-events';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { useDraftStore } from '@/features/editor/draft-context';
import { buildKeys } from '@/features/pdf/pdf-queries';
import { workspaceKeys } from '@/features/workspace/workspace-queries';
import type { FileChange } from '@/features/workspace/file-actions';
import { useProjectEvents } from './use-project-events';

export function useWorkspaceEvents(
  id: string,
  enabled: boolean,
  onChange: (change: FileChange, preserve: string[]) => void,
) {
  const client = useQueryClient();
  const drafts = useDraftStore();
  const { data: session } = useSession();
  const [connection, setConnection] = useState<EventConnection>('connecting');
  const [failure, setFailure] = useState<string>();
  const current = () =>
    client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id ===
    session?.user.id;
  async function invalidate(queryKey: QueryKey, exact = false) {
    // Загрузкой текста редактора управляет DraftStore: её нельзя отменять чужим refresh.
    const filter = {
      queryKey,
      exact,
      predicate: (query: { queryKey: QueryKey }) => query.queryKey[4] !== 'editor',
    };
    void client.invalidateQueries({ ...filter, refetchType: 'none' });
    await client.cancelQueries(filter);
    if (current()) await client.invalidateQueries(filter);
  }
  const retry = useProjectEvents(id, enabled, {
    status(value, message) {
      setConnection(value);
      setFailure(message);
    },
    connected() {
      // Снимки закрывают разрыв, если события уже вытеснены из журнала Redis.
      void invalidate(workspaceKeys.tree(id), true);
      void invalidate(workspaceKeys.project(id), true);
      void invalidate(buildKeys.latest(id), true);
      const latest = client.getQueryData<components['schemas']['BuildOut']>(buildKeys.latest(id));
      if (latest) void invalidate(buildKeys.build(latest.id));
      for (const draft of drafts.all())
        if (draft.project === id) void drafts.refresh(id, draft.path);
    },
    event(event) {
      if (!current()) return;
      switch (event.event) {
        case 'file.changed':
          void drafts.refresh(id, event.data.path, event.data.version);
          void invalidate(workspaceKeys.file(id, event.data.path));
          void invalidate(workspaceKeys.tree(id), true);
          break;
        case 'file.deleted':
        case 'file.moved': {
          const change: FileChange =
            event.event === 'file.deleted'
              ? { kind: 'delete', path: event.data.path }
              : { kind: 'move', from: event.data.from, to: event.data.to };
          const path = change.kind === 'delete' ? change.path : change.from;
          const preserve = drafts
            .pending()
            .filter((draft) => draft.project === id)
            .map((draft) => draft.path);
          drafts.removedExternally(id, path);
          onChange(change, preserve);
          void invalidate(['projects', id, 'file']);
          void invalidate(workspaceKeys.tree(id), true);
          break;
        }
        case 'build.started':
        case 'build.finished':
          void invalidate(buildKeys.latest(id), true);
          void invalidate(buildKeys.build(event.data.build_id));
          break;
        case 'material.ready':
          void invalidate(['projects', id, 'material-text', event.data.path]);
          break;
      }
    },
  });
  return { connection, retry, failure };
}
