import { useQuery } from '@tanstack/react-query';
import { ApiError } from '@/api/api-error';
import { api } from '@/api/client';

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
