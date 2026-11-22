import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/api/api-error';
import { api } from '@/api/client';
import type { components } from '@/api/schema';
import { sessionKey, useSession } from '@/features/auth/use-session';

export type Plan = components['schemas']['PlanOut'];
type PlanUpdate = components['schemas']['PlanUpdate'];

const planPath = '/api/v1/projects/{pid}/plan';
export const planKey = (id: string) => ['projects', id, 'plan'] as const;

export function useReportPlan(id: string, enabled: boolean) {
  return useQuery({
    queryKey: planKey(id),
    enabled,
    queryFn: async ({ signal }) => {
      try {
        const { data } = await api.GET(planPath, { params: { path: { pid: id } }, signal });
        if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать план отчёта.');
        return data;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}

export async function makeReportPlan(id: string) {
  const { data } = await api.POST(planPath, { params: { path: { pid: id } } });
  if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил запуск.');
  return data;
}

export async function confirmReportPlan(id: string) {
  const { data } = await api.POST('/api/v1/projects/{pid}/plan/confirm', {
    params: { path: { pid: id } },
  });
  if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил запуск отчёта.');
  return data;
}

export function useSaveReportPlan(id: string) {
  const client = useQueryClient();
  const { data: session } = useSession();
  const owner = session?.user.id;
  const current = () =>
    Boolean(owner) &&
    client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id === owner;
  const queryKey = planKey(id);

  return useMutation({
    meta: { sessionUserId: owner, inlineErrors: true },
    mutationFn: async (body: PlanUpdate) => {
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      const { data } = await api.PUT(planPath, { params: { path: { pid: id } }, body });
      if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось сохранить план.');
      return data;
    },
    async onSuccess(data) {
      if (!current()) return;
      await client.cancelQueries({ queryKey, exact: true });
      if (!current()) return;
      // Перечитываем план: пока сохраняли, могли измениться материалы проекта.
      client.setQueryData(queryKey, data);
      void client.invalidateQueries({ queryKey, exact: true });
    },
  });
}
