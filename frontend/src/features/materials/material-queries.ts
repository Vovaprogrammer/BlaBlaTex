import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { ProjectFile } from '@/features/workspace/file-tree-data';
import { workspaceKeys } from '@/features/workspace/workspace-queries';

export function useMaterialText(id: string, file: ProjectFile, offset = 0, limit = 20_000) {
  return useQuery({
    queryKey: ['projects', id, 'material-text', file.path, file.version, offset, limit],
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/projects/{pid}/material-text', {
        params: { path: { pid: id }, query: { path: file.path, offset, limit } },
        signal,
      });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Не удалось прочитать статус материала.');
      return data;
    },
    refetchInterval: (query) => (query.state.data?.status === 'pending' ? 5000 : false),
  });
}
export function useProjectBlob(id: string, file: ProjectFile, enabled = true) {
  return useQuery({
    queryKey: [...workspaceKeys.file(id, file.path), 'blob', file.version],
    enabled,
    gcTime: 60_000,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/projects/{pid}/files/{path}', {
        params: { path: { pid: id, path: file.path } },
        parseAs: 'blob',
        signal,
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось загрузить файл.');
      return data;
    },
  });
}
