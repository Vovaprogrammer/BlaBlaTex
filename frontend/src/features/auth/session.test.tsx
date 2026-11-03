import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, test } from 'vitest';
import { renderApp } from '@/test/render-app';
import { mockState, demoPassword } from '@/mocks/data';
import { failure } from '@/mocks/responses';
import { server } from '@/test/server';
import { returnPath } from './session-actions';

test('гость после входа возвращается на запрошенную защищённую страницу', async () => {
  mockState.current.currentUserId = null;
  renderApp('/settings?tab=account#section');
  await screen.findByRole('heading', { name: 'Войти в аккаунт' });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'student@example.com' } });
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: demoPassword } });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Войти' }));
  expect(await screen.findByRole('heading', { name: 'Настройки' })).toBeInTheDocument();
});

test('выход удаляет личный кэш и запрещает повторное открытие профиля', async () => {
  const { client } = renderApp('/projects');
  await screen.findByRole('heading', { name: 'Ваши проекты' });
  client.setQueryData(['private'], 'previous-user');
  await userEvent.setup().click(screen.getByRole('button', { name: 'Выйти' }));
  expect(await screen.findByRole('heading', { name: 'Войти в аккаунт' })).toBeInTheDocument();
  expect(client.getQueryData(['private'])).toBeUndefined();
  expect(client.getQueryData(['session'])).toBeNull();
  expect(mockState.current.currentUserId).toBeNull();
});

test('сбой выхода сохраняет сессию и позволяет повторить выход', async () => {
  server.use(
    http.post('/api/v1/auth/logout', () => failure(500, 'internal', 'Выход временно недоступен')),
  );
  renderApp('/projects');
  await screen.findByRole('heading', { name: 'Ваши проекты' });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Выйти' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Выход временно недоступен');
  expect(screen.getByRole('heading', { name: 'Ваши проекты' })).toBeInTheDocument();
  server.resetHandlers();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Выйти' }));
  expect(await screen.findByRole('heading', { name: 'Войти в аккаунт' })).toBeInTheDocument();
});

test('новая загрузка приложения восстанавливает вход через /auth/me', async () => {
  const first = renderApp('/projects');
  await screen.findByRole('heading', { name: 'Ваши проекты' });
  first.unmount();
  const next = renderApp('/profile');
  expect(await screen.findByRole('heading', { name: 'Профиль' })).toBeInTheDocument();
  expect(next.client.getQueryData(['session'])).toMatchObject({
    user: { email: 'student@example.com' },
  });
});

test.each(['https://example.com', '//example.com', '/\\example.com', '/login', '/unknown'])(
  'адрес возврата %s не используется',
  (from) => {
    expect(returnPath({ from })).toBe('/projects');
  },
);

test('безопасный адрес возврата сохраняет параметры и якорь', () => {
  expect(returnPath({ from: '/settings?tab=account#section' })).toBe(
    '/settings?tab=account#section',
  );
});
