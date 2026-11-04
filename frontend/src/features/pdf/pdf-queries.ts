import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';

export const buildKeys = {
  latest: (id: string) => ['projects', id, 'builds', 'latest'] as const,
  build: (id: string) => ['builds', id] as const,
  pdf: (id: string) => ['builds', id, 'pdf'] as const,
};
export function useLatestBuild(id: string) {
  return useQuery({
    queryKey: buildKeys.latest(id),
    staleTime: 0,
    queryFn: async ({ signal }) => {
      try {
        const { data } = await api.GET('/api/v1/projects/{pid}/builds/latest', {
          params: { path: { pid: id } },
          signal,
        });
        if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать сборку.');
        return data;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}
export function usePdf(id?: string) {
  return useQuery({
    queryKey: buildKeys.pdf(id ?? ''),
    enabled: Boolean(id),
    staleTime: Infinity,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/builds/{bid}/pdf', {
        params: { path: { bid: id! } },
        parseAs: 'blob',
        signal,
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не прислал PDF.');
      return data;
    },
  });
}
