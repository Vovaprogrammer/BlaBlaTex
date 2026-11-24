import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { useDraftStore } from '@/features/editor/draft-context';
import { buildKeys } from '@/features/pdf/pdf-queries';

export const checksKey = (id: string) => ['projects', id, 'checks'] as const;
export function useChecks(id: string, enabled: boolean) {
  const client = useQueryClient();
  const drafts = useDraftStore();
  const { data: session } = useSession();
  return useQuery<components['schemas']['CheckResult']>({
    queryKey: checksKey(id),
    enabled,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      enabled && !query.state.error && query.state.data?.pdf_checked === false ? 3000 : false,
    queryFn: async ({ signal }) => {
      await drafts.flush(id);
      signal.throwIfAborted();
      if (
        !session?.user.id ||
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
          session.user.id
      )
        throw new DOMException('Сессия изменилась', 'AbortError');
      const { data } = await api.POST('/api/v1/projects/{pid}/checks', {
        params: { path: { pid: id }, query: { wait: 0 } },
        signal,
      });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Сервер не прислал результаты проверки.');
      if (!signal.aborted) {
        void client.invalidateQueries({ queryKey: buildKeys.latest(id), exact: true });
        void client.invalidateQueries({ queryKey: buildKeys.successful(id), exact: true });
      }
      return data;
    },
  });
}
