import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import { sessionKey } from '@/features/auth/use-session';
import { demoId, demoPassword, mockState } from '@/mocks/data';
import { failure } from '@/mocks/responses';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';

async function openDialog() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Удалить аккаунт' }));
  return { user, dialog: await screen.findByRole('alertdialog', { name: 'Удалить аккаунт?' }) };
}

test('неверный пароль показывается у поля, аккаунт остаётся', async () => {
  renderApp('/settings');
  const { user, dialog } = await openDialog();
  await user.type(within(dialog).getByLabelText('Пароль'), 'wrong-password');
  await user.click(within(dialog).getByRole('button', { name: 'Удалить навсегда' }));
  expect(await within(dialog).findByText('Неверный пароль')).toBeInTheDocument();
  expect(mockState.current.accounts.has(demoId)).toBe(true);
});

test('после удаления аккаунта сайт открывает вход, данных аккаунта больше нет', async () => {
  const { client } = renderApp('/settings');
  const { user, dialog } = await openDialog();
  await user.type(within(dialog).getByLabelText('Пароль'), demoPassword);
  await user.click(within(dialog).getByRole('button', { name: 'Удалить навсегда' }));
  expect(await screen.findByRole('heading', { name: 'Войти в аккаунт' })).toBeInTheDocument();
  expect(client.getQueryData(sessionKey)).toBeNull();
  expect(mockState.current.accounts.has(demoId)).toBe(false);
  expect([...mockState.current.projects.values()].some((item) => item.owner === demoId)).toBe(
    false,
  );
});

test('пока ИИ работает, удаление предлагает его остановить', async () => {
  const runId = crypto.randomUUID();
  const cancelled: string[] = [];
  server.use(
    http.delete('/api/v1/account', () =>
      failure(
        423,
        'project_locked',
        'ИИ сейчас работает в проекте «Учебный отчёт». Остановите его и повторите удаление аккаунта',
        { run_id: runId },
      ),
    ),
    http.post('/api/v1/runs/:rid/cancel', ({ params }) => {
      cancelled.push(String(params.rid));
      return HttpResponse.json({ id: runId, status: 'cancelled' });
    }),
  );
  renderApp('/settings');
  const { user, dialog } = await openDialog();
  await user.type(within(dialog).getByLabelText('Пароль'), demoPassword);
  await user.click(within(dialog).getByRole('button', { name: 'Удалить навсегда' }));
  expect(
    await within(dialog).findByText(/ИИ сейчас работает в проекте «Учебный отчёт»/),
  ).toBeInTheDocument();
  await user.click(within(dialog).getByRole('button', { name: 'Остановить ИИ' }));
  expect(await within(dialog).findByText(/ИИ останавливается/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/ИИ сейчас работает/)).not.toBeInTheDocument();
  expect(cancelled).toEqual([runId]);
  expect(mockState.current.accounts.has(demoId)).toBe(true);
});

test('без пароля запрос не уходит, «Отмена» стирает введённый пароль', async () => {
  const requests: string[] = [];
  server.use(
    http.delete('/api/v1/account', ({ request }) => {
      requests.push(request.url);
    }),
  );
  renderApp('/settings');
  const { user, dialog } = await openDialog();
  await user.click(within(dialog).getByRole('button', { name: 'Удалить навсегда' }));
  expect(await within(dialog).findByText('Введите пароль')).toBeInTheDocument();
  expect(requests).toEqual([]);
  await user.type(within(dialog).getByLabelText('Пароль'), 'typed-password');
  await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));
  const reopened = await openDialog();
  expect(within(reopened.dialog).getByLabelText('Пароль')).toHaveValue('');
});

test('ошибка сервера без поля показывается в диалоге', async () => {
  server.use(
    http.delete('/api/v1/account', () =>
      failure(429, 'rate_limited', 'Слишком много попыток. Повторите через 15 мин'),
    ),
  );
  renderApp('/settings');
  const { user, dialog } = await openDialog();
  await user.type(within(dialog).getByLabelText('Пароль'), demoPassword);
  await user.click(within(dialog).getByRole('button', { name: 'Удалить навсегда' }));
  expect(await within(dialog).findByText(/Слишком много попыток/)).toBeInTheDocument();
  expect(within(dialog).queryByRole('button', { name: 'Остановить ИИ' })).not.toBeInTheDocument();
});
