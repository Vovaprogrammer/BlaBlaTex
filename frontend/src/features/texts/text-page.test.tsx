import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import { mockState } from '@/mocks/data';
import { renderApp } from '@/test/render-app';

test.each([
  ['/consent', 'Согласие на обработку персональных данных'],
  ['/privacy', 'Политика конфиденциальности'],
  ['/help', 'Отчёт за 5 минут'],
])('%s открывается без входа', async (path, title) => {
  mockState.current.currentUserId = null;
  renderApp(path);
  expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Войти в аккаунт' })).not.toBeInTheDocument();
});

test('ссылка из согласия открывает политику на сайте, внешняя — в новой вкладке', async () => {
  mockState.current.currentUserId = null;
  renderApp('/consent');
  const user = userEvent.setup();
  const [inText] = await screen.findAllByRole('link', { name: 'политике конфиденциальности' });
  await user.click(inText!);
  expect(
    await screen.findByRole('heading', { level: 1, name: 'Политика конфиденциальности' }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('link', { name: 'Помощь' }));
  const guide = await screen.findByRole('link', { name: /руководство по API/ });
  expect(guide).toHaveAttribute('target', '_blank');
  expect(guide).toHaveAttribute('rel', 'noreferrer');
});

test('в меню приложения есть помощь', async () => {
  renderApp('/projects');
  expect(await screen.findByRole('link', { name: 'Помощь' })).toHaveAttribute('href', '/help');
});
