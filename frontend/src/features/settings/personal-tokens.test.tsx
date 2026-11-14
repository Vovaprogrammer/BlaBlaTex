import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, test, vi } from 'vitest';
import { failure } from '@/mocks/responses';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';

test('токен виден и копируется только после создания, затем его можно отозвать', async () => {
  const user = userEvent.setup();
  const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
  const { client } = renderApp('/settings');
  const section = within(await screen.findByRole('region', { name: 'Личные токены' }));
  await section.findByText('Личных токенов пока нет.');
  await user.type(section.getByLabelText('Название токена (необязательно)'), 'Редактор');
  await user.click(section.getByRole('button', { name: 'Создать токен' }));
  const value = await section.findByLabelText<HTMLInputElement>('Значение нового токена');
  expect(value.value).toMatch(/^demo_only_/);
  await user.click(section.getByRole('button', { name: 'Скопировать' }));
  expect(copy).toHaveBeenCalledWith(value.value);
  expect(JSON.stringify(client.getQueriesData({ queryKey: ['settings', 'tokens'] }))).not.toContain(
    value.value,
  );
  expect(
    client
      .getMutationCache()
      .getAll()
      .map((item) => item.state.data),
  ).not.toContain(value.value);
  await user.click(section.getByRole('button', { name: 'Закрыть значение токена' }));
  expect(value).not.toBeInTheDocument();

  const row = within(section.getByRole('list', { name: 'Активные токены' }));
  expect(row.getByText('Ещё не использовался')).toBeInTheDocument();
  const button = row.getByRole('button', { name: 'Отозвать токен «Редактор»' });
  await user.click(button);
  let dialog = within(await screen.findByRole('alertdialog', { name: 'Отозвать токен' }));
  await user.click(dialog.getByRole('button', { name: 'Отмена' }));
  expect(button).toBeInTheDocument();
  await user.click(button);
  dialog = within(await screen.findByRole('alertdialog', { name: 'Отозвать токен' }));
  await user.click(dialog.getByRole('button', { name: 'Отозвать токен' }));
  expect(await section.findByText('Личных токенов пока нет.')).toBeInTheDocument();
});

test('ошибки создания и отзыва показаны рядом с действием', async () => {
  const item = {
    id: '00000000-0000-4000-8000-000000000013',
    name: 'Редактор',
    created_at: '2026-01-01T00:00:00Z',
    last_used_at: '2026-01-02T00:00:00Z',
  };
  server.use(
    http.get('/api/v1/tokens', () => HttpResponse.json({ items: [item] })),
    http.post('/api/v1/tokens', () => failure(403, 'forbidden', 'Достигнут лимит токенов')),
    http.delete('/api/v1/tokens/:tid', () => failure(500, 'internal', 'Не удалось отозвать токен')),
  );
  renderApp('/settings');
  const user = userEvent.setup();
  const section = within(await screen.findByRole('region', { name: 'Личные токены' }));
  expect(await section.findByText(/Последнее использование/)).toBeInTheDocument();
  const name = section.getByLabelText('Название токена (необязательно)');
  await user.type(name, 'Новый');
  await user.click(section.getByRole('button', { name: 'Создать токен' }));
  expect(await section.findByRole('alert')).toHaveTextContent('Достигнут лимит токенов');
  expect(name).toHaveValue('Новый');
  await user.click(section.getByRole('button', { name: 'Отозвать токен «Редактор»' }));
  const dialog = within(await screen.findByRole('alertdialog'));
  await user.click(dialog.getByRole('button', { name: 'Отозвать токен' }));
  expect(await dialog.findByRole('alert')).toHaveTextContent('Не удалось отозвать токен');
  await user.click(dialog.getByRole('button', { name: 'Отмена' }));
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  expect(section.getByText('Редактор')).toBeInTheDocument();
});
