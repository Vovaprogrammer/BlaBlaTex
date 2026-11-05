import { act, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import { demoId, timestamp } from '@/mocks/data';
import { emitMockEvent } from '@/mocks/project-events';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import type { Message, Run } from './chat-data';

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
