import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import { demoId, timestamp } from '@/mocks/data';
import { failure } from '@/mocks/responses';
import { emitMockEvent } from '@/mocks/project-events';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import type { Message, Run } from './chat-data';

test('Shift+Enter добавляет строку, Enter отправляет, остановка завершает текущий ответ', async () => {
  const user = userEvent.setup();
  renderApp(`/projects/${demoId}`);
  const input = await screen.findByRole('textbox', { name: 'Сообщение' });
  await screen.findByText('Опишите, что нужно сделать с документом.');
  input.focus();
  await user.keyboard('Первая строка{Shift>}{Enter}{/Shift}Вторая строка');
  expect(input).toHaveValue('Первая строка\nВторая строка');
  await user.keyboard('{Enter}');
  const list = within(screen.getByRole('region', { name: 'Сообщения' }));
  expect(await list.findByText('Первая строка Вторая строка')).toBeInTheDocument();
  const stop = await screen.findByRole('button', { name: 'Остановить' });
  expect(input).toHaveValue('');
  await user.click(stop);
  expect(await screen.findByRole('button', { name: 'Отправить' })).toBeDisabled();
  expect(await list.findByText('Ответ остановлен.')).toBeInTheDocument();
});

test('ошибка отправки показана рядом с полем и сохраняет черновик', async () => {
  server.use(
    http.post('/api/v1/projects/:pid/messages', () =>
      failure(500, 'internal', 'Очередь временно недоступна'),
    ),
  );
  renderApp(`/projects/${demoId}`);
  const user = userEvent.setup();
  const composer = within(await screen.findByRole('form', { name: 'Написать сообщение' }));
  const input = composer.getByRole('textbox');
  await screen.findByText('Опишите, что нужно сделать с документом.');
  input.focus();
  await user.keyboard('Мой черновик{Enter}');
  expect(await composer.findByRole('alert')).toHaveTextContent('Очередь временно недоступна');
  expect(input).toHaveValue('Мой черновик');
});

const run: Run = {
  id: '00000000-0000-4000-8000-000000000010',
  status: 'running',
  message_id: '00000000-0000-4000-8000-000000000011',
  changeset_id: '00000000-0000-4000-8000-000000000012',
  created_at: timestamp,
  finished_at: null,
  error: null,
};
const assistant = (text: string, seq: number, status: Message['status'] = 'running'): Message => ({
  id: run.message_id,
  run_id: run.id,
  role: 'assistant',
  status,
  created_at: timestamp,
  parts: [{ type: 'text', text }],
  seq,
});
const delta = (seq: number, text: string) =>
  act(() =>
    emitMockEvent(demoId, {
      event: 'run.delta',
      data: { run_id: run.id, message_id: run.message_id, seq, text },
    }),
  );

test('лента отображает Markdown и формулы, применяет только новые события и сверяет итог с сервером', async () => {
  let item = assistant('**Итог:** $x^2$.', 1);
  server.use(
    http.get('/api/v1/projects/:pid/messages', () =>
      HttpResponse.json({
        items: [item],
        has_more: false,
        active_run: item.status === 'done' ? null : run,
      }),
    ),
  );
  renderApp(`/projects/${demoId}`);
  const list = within(await screen.findByRole('region', { name: 'Сообщения' }));
  const bold = await list.findByText('Итог:');
  expect(bold.tagName).toBe('STRONG');
  expect(bold.closest('article')?.querySelector('.katex')).toBeInTheDocument();
  await screen.findByText('Обновления подключены');
  await delta(1, 'Повтор');
  await delta(2, '\n\nПромежуточный ответ');
  expect(await list.findByText('Промежуточный ответ')).toBeInTheDocument();
  expect(list.queryByText(/Повтор/)).not.toBeInTheDocument();

  item = assistant('Окончательный ответ', 2, 'done');
  await act(() =>
    emitMockEvent(demoId, {
      event: 'run.finished',
      data: {
        run_id: run.id,
        status: 'done',
        changeset_id: run.changeset_id,
        usage: { tokens_in: 0, tokens_out: 0 },
      },
    }),
  );
  expect(await list.findByText('Окончательный ответ')).toBeInTheDocument();
  expect(list.queryByText('Промежуточный ответ')).not.toBeInTheDocument();
});

test('пропуск события восстанавливается из снимка без повторения текста', async () => {
  let item = assistant('Начало.', 1);
  server.use(
    http.get('/api/v1/projects/:pid/messages', () =>
      HttpResponse.json({
        items: [item],
        has_more: false,
        active_run: run,
      }),
    ),
  );
  renderApp(`/projects/${demoId}`);
  await screen.findByText('Начало.');
  await screen.findByText('Обновления подключены');
  item = assistant('Начало. Середина.', 2);
  await delta(3, ' Конец.');
  await waitFor(() => expect(screen.getByText('Начало. Середина. Конец.')).toBeInTheDocument());
});

test('при повторном открытии восстанавливается работающий ответ, сборка и итоговая ошибка', async () => {
  let item = assistant('Часть ответа.', 0);
  server.use(
    http.get('/api/v1/projects/:pid/messages', () =>
      HttpResponse.json({
        items: [item],
        has_more: false,
        active_run: item.status === 'failed' ? null : run,
      }),
    ),
  );
  const first = renderApp(`/projects/${demoId}`);
  await screen.findByText('Думает…');
  first.unmount();
  renderApp(`/projects/${demoId}`);
  await screen.findByRole('button', { name: 'Остановить' });
  await screen.findByText('Обновления подключены');
  await act(() =>
    emitMockEvent(demoId, {
      event: 'run.tool_call',
      data: {
        run_id: run.id,
        call_id: 'compile-1',
        seq: 1,
        tool: 'compile',
        summary: 'Собираем документ',
      },
    }),
  );
  expect(await screen.findByText('Собирает PDF…')).toBeInTheDocument();
  const card = screen.getByText('Собираем документ');
  expect(card.closest('details')).not.toHaveAttribute('open');
  await userEvent.setup().click(card);
  expect(card.closest('details')).toHaveAttribute('open');
  await act(() =>
    emitMockEvent(demoId, {
      event: 'run.tool_result',
      data: {
        run_id: run.id,
        call_id: 'compile-1',
        seq: 2,
        ok: false,
        summary: 'Ошибка сборки',
      },
    }),
  );
  expect(await screen.findByText('Думает…')).toBeInTheDocument();
  expect(await screen.findByText('Ошибка сборки')).toBeVisible();
  item = {
    ...item,
    seq: 2,
    status: 'failed',
    parts: [...item.parts, { type: 'error', text: 'Сборка прервана.' }],
  };
  await act(() =>
    emitMockEvent(demoId, {
      event: 'run.finished',
      data: {
        run_id: run.id,
        status: 'failed',
        changeset_id: run.changeset_id,
        usage: { tokens_in: 0, tokens_out: 0 },
      },
    }),
  );
  const list = within(screen.getByRole('region', { name: 'Сообщения' }));
  expect(await list.findByRole('alert')).toHaveTextContent('Сборка прервана.');
  expect(screen.queryByRole('button', { name: 'Остановить' })).not.toBeInTheDocument();
});

test('история запрашивает предыдущую страницу по ID и добавляет её перед текущей', async () => {
  const newer = assistant('Новое сообщение', 0, 'done');
  const older = { ...newer, id: 'older', parts: [{ type: 'text', text: 'Раннее сообщение' }] };
  let cursor: string | null = null;
  server.use(
    http.get('/api/v1/projects/:pid/messages', ({ request }) => {
      const before = new URL(request.url).searchParams.get('before');
      if (before) cursor = before;
      return HttpResponse.json({
        items: before === newer.id ? [older] : [newer],
        has_more: !before,
        active_run: null,
      });
    }),
  );
  renderApp(`/projects/${demoId}`);
  const list = within(await screen.findByRole('region', { name: 'Сообщения' }));
  await userEvent
    .setup()
    .click(await list.findByRole('button', { name: 'Показать более ранние сообщения' }));
  await list.findByText('Раннее сообщение');
  expect(cursor).toBe(newer.id);
  expect(list.getAllByRole('article').map((article) => article.textContent)).toEqual([
    expect.stringContaining('Раннее сообщение'),
    expect.stringContaining('Новое сообщение'),
  ]);
  expect(
    list.queryByRole('button', { name: 'Показать более ранние сообщения' }),
  ).not.toBeInTheDocument();
});
