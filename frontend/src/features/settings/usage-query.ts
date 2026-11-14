import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';

export const usageKey = ['usage'] as const;

export function useUsage() {
  return useQuery({
    queryKey: usageKey,
    refetchInterval: 60_000,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/usage', { signal });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Сервер не прислал данные о расходе ИИ.');
      return data;
    },
  });
}
