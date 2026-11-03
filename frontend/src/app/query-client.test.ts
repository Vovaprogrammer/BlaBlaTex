import { MutationObserver } from '@tanstack/react-query';
import { afterEach, expect, test, vi } from 'vitest';
import { toast } from 'sonner';
import { ApiError } from '@/api/api-error';
import { createQueryClient } from './query-client';

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));
const clients: ReturnType<typeof createQueryClient>[] = [];
function makeClient(redirect = vi.fn()) {
  const client = createQueryClient(redirect);
  clients.push(client);
  return client;
}
afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
  vi.clearAllMocks();
});

test('401 очищает кэш предыдущего пользователя и переводит на вход', async () => {
  const redirect = vi.fn();
  const client = makeClient(redirect);
  client.setQueryData(['private-projects'], { private: true });
  await expect(
    client.fetchQuery({
      queryKey: ['expired'],
      queryFn: () => {
        throw new ApiError(401, 'unauthorized', 'Нужно войти в аккаунт');
      },
    }),
  ).rejects.toBeInstanceOf(ApiError);
  expect(redirect).toHaveBeenCalledOnce();
  expect(client.getQueryData(['private-projects'])).toBeUndefined();
  expect(toast.error).not.toHaveBeenCalled();
});

test('ошибка чтения показывается сообщением сервера без повторных запросов', async () => {
  const client = makeClient();
  const queryFn = vi.fn(() => {
    throw new ApiError(403, 'forbidden', 'Файл создаётся автоматически');
  });
  await expect(client.fetchQuery({ queryKey: ['file'], queryFn })).rejects.toBeInstanceOf(ApiError);
  expect(queryFn).toHaveBeenCalledOnce();
  expect(toast.error).toHaveBeenCalledWith('Файл создаётся автоматически', { id: 'api-error' });
});

test('ошибка изменения данных тоже показывается сообщением сервера', async () => {
  const client = makeClient();
  const mutation = new MutationObserver(client, {
    mutationFn: async () => {
      throw new ApiError(422, 'validation_error', 'Проверьте введённые данные');
    },
  });
  await expect(mutation.mutate()).rejects.toBeInstanceOf(ApiError);
  expect(toast.error).toHaveBeenCalledWith('Проверьте введённые данные', { id: 'api-error' });
});

test('неизвестная ошибка не раскрывает технический текст', async () => {
  const client = makeClient();
  await expect(
    client.fetchQuery({
      queryKey: ['unknown'],
      queryFn: () => {
        throw new Error('private implementation details');
      },
    }),
  ).rejects.toThrow();
  expect(toast.error).toHaveBeenCalledWith('Не удалось загрузить данные. Попробуйте ещё раз.', {
    id: 'api-error',
  });
});

test('поздняя ошибка запроса старого пользователя не сбрасывает новую сессию', async () => {
  const redirect = vi.fn();
  const client = makeClient(redirect);
  client.setQueryData(['session'], { user: { id: 'new-user' } });
  const mutation = new MutationObserver(client, {
    meta: { sessionUserId: 'old-user', formErrors: true },
    mutationFn: async () => {
      throw new ApiError(401, 'unauthorized', 'Старая сессия завершена');
    },
  });
  await expect(mutation.mutate()).rejects.toBeInstanceOf(ApiError);
  expect(redirect).not.toHaveBeenCalled();
  expect(client.getQueryData(['session'])).toEqual({ user: { id: 'new-user' } });
});

test('401 при сохранении профиля текущего пользователя завершает сессию', async () => {
  const redirect = vi.fn();
  const client = makeClient(redirect);
  client.setQueryData(['session'], { user: { id: 'current-user' } });
  const mutation = new MutationObserver(client, {
    meta: { sessionUserId: 'current-user', formErrors: true },
    mutationFn: async () => {
      throw new ApiError(401, 'unauthorized', 'Войдите снова');
    },
  });
  await expect(mutation.mutate()).rejects.toBeInstanceOf(ApiError);
  expect(redirect).toHaveBeenCalledOnce();
  expect(client.getQueryData(['session'])).toBeUndefined();
});
