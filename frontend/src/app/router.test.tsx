import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { delay, http, HttpResponse } from 'msw';
import { afterEach, expect, test } from 'vitest';
import { AppRoutes } from './router';
import { ThemeProvider } from './theme-provider';
import { createQueryClient } from './query-client';
import { server } from '@/test/server';
import { currentAccount, mockState } from '@/mocks/data';
import { failure } from '@/mocks/responses';

const clients: ReturnType<typeof createQueryClient>[] = [];
afterEach(() => clients.splice(0).forEach((client) => client.clear()));
function openPage(path: string) {
  const client = createQueryClient(() => {});
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return client;
}

test.each([
  ['/', 'Ваши проекты'],
  ['/projects', 'Ваши проекты'],
  ['/login', 'Войти в аккаунт'],
  ['/register', 'Создать аккаунт'],
  ['/profile', 'Профиль'],
  ['/settings', 'Настройки'],
  ['/projects/00000000-0000-4000-8000-000000000001', 'Рабочее окно'],
  ['/unknown', 'Страница не найдена'],
])('прямая ссылка %s открывает нужную страницу', async (path, heading) => {
  openPage(path);
  expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
});

test('переход между личными страницами сохраняет тему и выделяет раздел', async () => {
  openPage('/projects');
  await screen.findByRole('heading', { name: 'Ваши проекты' });
  const user = userEvent.setup();
  const previousTheme = document.documentElement.classList.contains('dark');
  await user.click(screen.getByRole('button', { name: /Включить .+ тему/ }));
  await user.click(screen.getByRole('link', { name: 'Профиль' }));
  expect(await screen.findByRole('heading', { name: 'Профиль' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Профиль' })).toHaveAttribute('aria-current', 'page');
  expect(document.documentElement.classList.contains('dark')).toBe(!previousTheme);
});

test.each(['/profile', '/projects', '/projects/example', '/settings'])(
  'без сессии %s переводит на вход',
  async (path) => {
    mockState.current.currentUserId = null;
    openPage(path);
    expect(await screen.findByRole('heading', { name: 'Войти в аккаунт' })).toBeInTheDocument();
    expect(
      screen.queryByRole('navigation', { name: 'Разделы приложения' }),
    ).not.toBeInTheDocument();
  },
);

test('ожидание проверки сессии не раскрывает защищённое содержимое', async () => {
  server.use(
    http.get('/api/v1/auth/me', async () => {
      await delay(100);
      const account = currentAccount()!;
      return HttpResponse.json({ user: account.user, profile: account.profile });
    }),
  );
  openPage('/projects');
  expect(screen.getByRole('status')).toHaveTextContent('Проверяем вход');
  expect(screen.queryByRole('heading', { name: 'Ваши проекты' })).not.toBeInTheDocument();
  expect(await screen.findByRole('heading', { name: 'Ваши проекты' })).toBeInTheDocument();
});

test('сбой сервера не выдаётся за выход из аккаунта; повтор восстанавливает страницу', async () => {
  server.use(http.get('/api/v1/auth/me', () => failure(500, 'internal', 'Попробуйте позже')));
  openPage('/projects');
  expect(await screen.findByRole('alert')).toHaveTextContent('Попробуйте позже');
  expect(screen.queryByRole('heading', { name: 'Войти в аккаунт' })).not.toBeInTheDocument();
  server.resetHandlers();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Повторить' }));
  expect(await screen.findByRole('heading', { name: 'Ваши проекты' })).toBeInTheDocument();
});

test('истёкшая сессия очищает личные данные перед показом входа', async () => {
  const client = openPage('/projects');
  await screen.findByRole('heading', { name: 'Ваши проекты' });
  client.setQueryData(['private-data'], { confidential: true });
  mockState.current.currentUserId = null;
  await act(() => client.invalidateQueries({ queryKey: ['session'] }));
  expect(await screen.findByRole('heading', { name: 'Войти в аккаунт' })).toBeInTheDocument();
  expect(client.getQueryData(['private-data'])).toBeUndefined();
});

test('гость может перейти между входом и регистрацией', async () => {
  mockState.current.currentUserId = null;
  openPage('/login');
  await userEvent.setup().click(screen.getByRole('link', { name: 'Зарегистрироваться' }));
  expect(screen.getByRole('heading', { name: 'Создать аккаунт' })).toBeInTheDocument();
});
