import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ApiError, isRecord } from '@/api/api-error';

export function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : 'Не удалось загрузить данные. Попробуйте ещё раз.';
}

export function createQueryClient(onUnauthorized: () => void) {
  function handleError(error: unknown) {
    if (error instanceof ApiError && error.status === 401) {
      client.clear();
      onUnauthorized();
      return;
    }
    toast.error(errorMessage(error), { id: 'api-error' });
  }
  const client = new QueryClient({
    queryCache: new QueryCache({ onError: handleError }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (mutation.meta?.editorSave) {
          const session = client.getQueryData<unknown>(['session']);
          const owner = isRecord(session) && isRecord(session.user) ? session.user.id : null;
          if (
            !isRecord(_variables) ||
            owner !== _variables.owner ||
            (error instanceof DOMException && error.name === 'AbortError')
          )
            return;
          if (error instanceof ApiError && [412, 423].includes(error.status)) return;
        }
        if (typeof mutation.meta?.sessionUserId === 'string') {
          const session = client.getQueryData<unknown>(['session']);
          const userId = isRecord(session) && isRecord(session.user) ? session.user.id : null;
          if (userId !== mutation.meta.sessionUserId) return;
        }
        if (
          error instanceof ApiError &&
          ((mutation.meta?.authForm && error.status === 401) ||
            (mutation.meta?.formErrors && [400, 409, 422].includes(error.status)))
        )
          return;
        handleError(error);
      },
    }),
    defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } },
  });
  return client;
}
