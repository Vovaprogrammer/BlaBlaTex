import { useEffect } from 'react';
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
  const successful = useLatestBuild(id, 'ok');
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
  const activePdf = active?.status === 'ok' && active.has_pdf ? active : null;
  const previousPdf = successful.data?.has_pdf ? successful.data : null;
  const shownPdf =
    activePdf &&
    (!previousPdf || Date.parse(activePdf.created_at) >= Date.parse(previousPdf.created_at))
      ? activePdf
      : previousPdf;
  useEffect(() => {
    if (!activePdf || !session?.user.id) return;
    // Запоздавший GET успешной сборки не должен затереть новый результат из опроса.
    void client.cancelQueries({ queryKey: buildKeys.successful(id), exact: true }).then(() => {
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
        return;
      client.setQueryData<Build | null>(buildKeys.successful(id), (previous) =>
        previous && Date.parse(previous.created_at) > Date.parse(activePdf.created_at)
          ? previous
          : activePdf,
      );
    });
  }, [activePdf, client, id, session?.user.id]);
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
  return {
    latest,
    successful,
    current,
    active,
    shownPdf,
    start,
    busy: start.isPending || isBuilding(active),
  };
}
export type BuildController = ReturnType<typeof useBuild>;
