import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';

export const sessionKey = ['session'] as const;

export function useSession() {
  const client = useQueryClient();
  return useQuery({
    queryKey: sessionKey,
    queryFn: async ({ signal }) => {
      try {
        const { data } = await api.GET('/api/v1/auth/me', { signal });
        if (!data)
          throw new ApiError(
            0,
            'invalid_response',
            'Сервер вернул пустой ответ. Попробуйте ещё раз.',
          );
        return data;
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        client.removeQueries({ predicate: (query) => query.queryKey[0] !== sessionKey[0] });
        client.getMutationCache().clear();
        return null;
      }
    },
  });
}
