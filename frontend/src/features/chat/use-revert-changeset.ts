import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError, isRecord } from '@/api/api-error';
import type { components } from '@/api/schema';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { useDraftStore } from '@/features/editor/draft-context';
import { workspaceKeys } from '@/features/workspace/workspace-queries';

type Schemas = components['schemas'];
type File = Schemas['FileDiff'];

export function revertConflicts(error: unknown): Schemas['RevertConflictFile'][] {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== 'revert_conflict')
    return [];
  if (!Array.isArray(error.details.files)) return [];
  return error.details.files.flatMap((file: unknown) => {
    if (!isRecord(file) || typeof file.path !== 'string') return [];
    const { path, reason } = file;
    return reason === 'changed' || reason === 'path_taken' ? [{ path, reason }] : [];
  });
}

export function useRevertChangeset(project: string, id: string) {
  const client = useQueryClient();
  const drafts = useDraftStore();
  const { data: session } = useSession();
  const owner = session?.user.id;
  const current = () =>
    Boolean(owner) &&
    client.getQueryData<Schemas['MeResponse'] | null>(sessionKey)?.user.id === owner;
  return useMutation({
    meta: { sessionUserId: owner, formErrors: true },
    mutationFn: async (files: File[]) => {
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      for (const file of files) {
        drafts.assertCanChange(project, file.path);
        if (file.old_path) drafts.assertCanChange(project, file.old_path);
      }
      const { data } = await api.POST('/api/v1/changesets/{cid}/revert', {
        params: { path: { cid: id } },
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил откат.');
      return data;
    },
    onSuccess: async (_, files) => {
      if (!current()) return;
      // SSE переносит вкладки. Запросы обновляют данные и при разрыве соединения.
      const paths = files.flatMap(({ path, old_path }) => (old_path ? [path, old_path] : [path]));
      for (const draft of drafts.all()) {
        if (draft.project !== project) continue;
        if (paths.some((path) => draft.path === path || draft.path.startsWith(path + '/')))
          void drafts.refresh(project, draft.path);
      }
      await Promise.all([
        client.invalidateQueries({ queryKey: workspaceKeys.tree(project), exact: true }),
        client.invalidateQueries({
          queryKey: ['projects', project, 'file'],
          predicate: (query) => query.queryKey[4] !== 'editor',
        }),
        client.invalidateQueries({ queryKey: ['projects', project, 'material-text'] }),
      ]);
    },
  });
}

export type RevertChangeset = ReturnType<typeof useRevertChangeset>;
