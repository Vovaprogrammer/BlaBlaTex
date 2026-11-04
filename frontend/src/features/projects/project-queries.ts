import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';

export const projectsKey = ['projects'] as const;
export function useProjects() {
  return useQuery({
    queryKey: projectsKey,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/projects', { signal });
      if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать список проектов.');
      return data;
    },
  });
}
