import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, test } from 'vitest';
import { invalid } from '@/mocks/responses';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';

test('ключ можно добавить, заменить и удалить, в настройках видны только последние четыре символа', async () => {
  renderApp('/settings');
  const user = userEvent.setup();
  const input = await screen.findByLabelText('Ключ API');
  await user.type(input, ' demo-key-1234 ');
  await user.click(screen.getByRole('button', { name: 'Сохранить ключ' }));
  expect(await screen.findByText('••••1234')).toBeInTheDocument();
  expect(await screen.findByRole('link', { name: 'ИИ · свой ключ' })).toBeInTheDocument();
  expect(input).toHaveValue('');
  await user.type(input, 'another-key-5678');
  await user.click(screen.getByRole('button', { name: 'Заменить ключ' }));
  expect(await screen.findByText('••••5678')).toBeInTheDocument();
  expect(screen.queryByText('••••1234')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Удалить ключ' }));
  expect(await screen.findByText('Ключ не добавлен.')).toBeInTheDocument();
  expect(await screen.findByRole('link', { name: /ИИ · 0 \/ .* токенов/ })).toBeInTheDocument();
});

test('отказ провайдера показывается у поля ключа', async () => {
  server.use(http.put('/api/v1/settings/llm-key', () => invalid('key', 'Провайдер отклонил ключ')));
  renderApp('/settings');
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('Ключ API'), 'rejected-key');
  await user.click(screen.getByRole('button', { name: 'Сохранить ключ' }));
  expect(await screen.findByText('Провайдер отклонил ключ')).toBeInTheDocument();
  expect(screen.getByText('Ключ не добавлен.')).toBeInTheDocument();
});
