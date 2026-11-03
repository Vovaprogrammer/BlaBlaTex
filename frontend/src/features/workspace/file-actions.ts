import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError, isRecord } from '@/api/api-error';
import { errorMessage } from '@/app/query-client';
import { useSession, sessionKey } from '@/features/auth/use-session';
import type { components } from '@/api/schema';
import { workspaceKeys } from './workspace-queries';
import { joinPath, parentPath } from './file-tree-data';

export type FileAction = {
  kind: 'create-file' | 'create-folder' | 'rename' | 'move' | 'delete';
  path: string;
  folder?: boolean;
};
export type FileChange =
  | { kind: 'create'; path: string; folder?: boolean }
  | { kind: 'move'; from: string; to: string }
  | { kind: 'delete'; path: string };

export function fileErrorMessage(error: unknown) {
  if (error instanceof ApiError && Array.isArray(error.details.errors)) {
    const first = error.details.errors.find(
      (issue) => isRecord(issue) && typeof issue.message === 'string',
    );
    if (isRecord(first) && typeof first.message === 'string') return first.message;
  }
  return errorMessage(error);
}

export function useFileAction(id: string, onChange: (change: FileChange) => void) {
  const client = useQueryClient();
  const { data: session } = useSession();
  return useMutation({
    mutationKey: ['projects', id, 'files'],
    meta: { formErrors: true, sessionUserId: session?.user.id },
    mutationFn: async ({
      action,
      value,
    }: {
      action: FileAction;
      value: string;
    }): Promise<FileChange> => {
      if (action.kind === 'delete') {
        await api.DELETE('/api/v1/projects/{pid}/files/{path}', {
          params: { path: { pid: id, path: action.path } },
        });
        return { kind: 'delete', path: action.path };
      }
      if (action.kind === 'rename' || action.kind === 'move') {
        const to = action.kind === 'rename' ? joinPath(parentPath(action.path), value) : value;
        const { data } = await api.POST('/api/v1/projects/{pid}/move', {
          params: { path: { pid: id } },
          body: { from: action.path, to },
        });
        if (!data)
          throw new ApiError(0, 'invalid_response', 'Не удалось прочитать результат переноса.');
        return { kind: 'move', from: action.path, to: data.path };
      }
      const path = joinPath(action.path, value);
      const response =
        action.kind === 'create-folder'
          ? await api.POST('/api/v1/projects/{pid}/folders', {
              params: { path: { pid: id } },
              body: { path },
            })
          : await api.PUT('/api/v1/projects/{pid}/files/{path}', {
              params: { path: { pid: id, path } },
              body: '',
              headers: { 'Content-Type': 'text/plain; charset=utf-8', 'If-None-Match': '*' },
            });
      if (!response.data)
        throw new ApiError(0, 'invalid_response', 'Не удалось прочитать результат создания.');
      return { kind: 'create', path: response.data.path, folder: response.data.kind === 'folder' };
    },
    onSuccess: async (change) => {
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
        return;
      onChange(change);
      await client.invalidateQueries({ queryKey: workspaceKeys.tree(id) });
    },
  });
}
