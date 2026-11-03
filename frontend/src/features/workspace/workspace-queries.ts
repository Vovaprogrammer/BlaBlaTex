import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';

export const workspaceKeys = {
  project: (id: string) => ['projects', id] as const,
  tree: (id: string) => ['projects', id, 'tree'] as const,
  file: (id: string, path: string) => ['projects', id, 'file', path] as const,
};
export function useProject(id: string) {
  return useQuery({
    queryKey: workspaceKeys.project(id),
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/projects/{pid}', {
        params: { path: { pid: id } },
        signal,
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать проект.');
      return data;
    },
  });
}
