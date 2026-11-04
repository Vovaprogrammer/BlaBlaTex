import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { useDraftStore } from '@/features/editor/draft-context';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { buildKeys, useLatestBuild } from './pdf-queries';

type Build = components['schemas']['BuildOut'];
export const isBuilding = (build?: Build | null) =>
  build?.status === 'queued' || build?.status === 'running';
export function useBuild(id: string) {
  const client = useQueryClient();
  const drafts = useDraftStore();
  const { data: session } = useSession();
  const latest = useLatestBuild(id);
  const [shownPdf, setShownPdf] = useState<Build | null>(null);
  const currentId = latest.data?.id;
  const current = useQuery({
    queryKey: buildKeys.build(currentId ?? ''),
    enabled: Boolean(currentId),
    initialData: latest.data?.id === currentId ? (latest.data ?? undefined) : undefined,
    staleTime: 0,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/builds/{bid}', {
        params: { path: { bid: currentId! } },
        signal,
      });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Не удалось прочитать состояние сборки.');
      return data;
    },
    refetchInterval: (query) => (isBuilding(query.state.data) ? 1000 : false),
  });
  const active = current.data ?? latest.data;
  useEffect(() => {
    if (active?.has_pdf) {
      // Запоминаем последний PDF из ответа API, пока следующая сборка не закончена.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setShownPdf(active);
    }
  }, [active]);
  const start = useMutation({
    meta: { sessionUserId: session?.user.id },
    mutationFn: async () => {
      await drafts.flush(id);
      await client.cancelQueries({ queryKey: buildKeys.latest(id), exact: true });
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
        throw new ApiError(0, 'session_changed', 'Сессия изменилась. Войдите заново.');
      const { data } = await api.POST('/api/v1/projects/{pid}/builds', {
        params: { path: { pid: id } },
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил запуск сборки.');
      return data;
    },
    onSuccess: async (data) => {
      await client.cancelQueries({ queryKey: buildKeys.latest(id), exact: true });
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
        return;
      client.setQueryData(buildKeys.build(data.id), data);
      client.setQueryData(buildKeys.latest(id), data);
    },
  });
  return { latest, current, active, shownPdf, start, busy: start.isPending || isBuilding(active) };
}
export type BuildController = ReturnType<typeof useBuild>;
