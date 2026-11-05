import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, test, vi } from 'vitest';
import type { components } from '@/api/schema';
import { demoId, mockState, timestamp } from '@/mocks/data';
import { emitMockEvent } from '@/mocks/project-events';
import { failure } from '@/mocks/responses';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { parseDiff } from './parse-diff';

const id = '00000000-0000-4000-8000-000000000050';
const diff =
  '--- a/main.tex\n+++ b/main.tex\n@@ -3,2 +3,2 @@\n Общая строка\n-Старый текст\n+Новый текст\n';
const changes: components['schemas']['ChangesetDiff'] = {
  changeset: {
    id,
    author: 'ai',
    message: null,
    run_id: null,
    reverts_id: null,
    reverted_by: null,
    created_at: timestamp,
    updated_at: timestamp,
  },
  files: [
    {
      path: 'main.tex',
      old_path: null,
      change: 'modified',
      kind: 'text',
      diff,
      additions: 1,
      deletions: 1,
      too_large: false,
    },
    {
      path: 'image.png',
      old_path: 'old.png',
      change: 'moved',
      kind: 'binary',
      diff: null,
      additions: 0,
      deletions: 0,
      too_large: false,
    },
  ],
};

function openProject() {
  server.use(
    http.get('/api/v1/projects/:pid/messages', () =>
      HttpResponse.json({
        items: [
          {
            id,
            role: 'assistant',
            run_id: null,
            status: 'done',
            seq: 0,
            created_at: timestamp,
            parts: [{ type: 'changeset', changeset_id: id }],
          },
        ],
        active_run: null,
        has_more: false,
      }),
    ),
    http.get('/api/v1/changesets/:cid/diff', () => HttpResponse.json(changes)),
  );
  return renderApp(`/projects/${demoId}`);
}

test('открывает сравнение из карточки и показывает перенос файла без текста', async () => {
  openProject();
  const user = userEvent.setup();
  expect(await screen.findByText('Изменено файлов: 2')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Посмотреть правки' }));
  const dialog = within(await screen.findByRole('dialog', { name: 'Правки агента' }));
  expect(dialog.getByRole('region', { name: 'Сравнение версий файла' })).toHaveTextContent(
    'Новый текст',
  );
  await user.selectOptions(dialog.getByRole('combobox', { name: 'Файл' }), '1');
  expect(dialog.getByText('Прежний путь: old.png')).toBeVisible();
  expect(dialog.getByText('Для этого изменения нет текстового сравнения.')).toBeVisible();
});

test('сохраняет границы фрагментов и отсутствие перевода строки в конце', () => {
  expect(parseDiff(diff + '@@ -8 +8 @@\n-старый\n+новый\n\\ No newline at end of file\n')).toEqual([
    {
      oldLine: 3,
      newLine: 3,
      before: 'Общая строка\nСтарый текст\n',
      after: 'Общая строка\nНовый текст\n',
    },
    { oldLine: 8, newLine: 8, before: 'старый\n', after: 'новый' },
  ]);
});

test('после перезагрузки отменённые правки не предлагают отменить снова', async () => {
  openProject();
  server.use(
    http.get('/api/v1/changesets/:cid/diff', () =>
      HttpResponse.json({
        ...changes,
        changeset: { ...changes.changeset, reverted_by: '00000000-0000-4000-8000-000000000054' },
      }),
    ),
  );
  const user = userEvent.setup();
  expect(await screen.findByText('Правки отменены.')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Посмотреть правки' }));
  const dialog = within(await screen.findByRole('dialog', { name: 'Правки агента' }));
  expect(dialog.getByRole('status')).toHaveTextContent('Правки отменены.');
  expect(dialog.queryByRole('button', { name: 'Отменить правки' })).not.toBeInTheDocument();
});

async function confirmRevert() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Посмотреть правки' }));
  await user.click(await screen.findByRole('button', { name: 'Отменить правки' }));
  const dialog = within(await screen.findByRole('dialog', { name: 'Отменить правки агента?' }));
  return { user, dialog };
}

test('показывает причины конфликта только после подтверждения отката', async () => {
  openProject();
  const post = vi.fn(() =>
    failure(409, 'revert_conflict', 'Часть файлов уже изменилась.', {
      files: [
        { path: 'main.tex', reason: 'changed' },
        { path: 'old.png', reason: 'path_taken' },
      ],
    }),
  );
  server.use(http.post('/api/v1/changesets/:cid/revert', post));
  const { user, dialog } = await confirmRevert();
  expect(post).not.toHaveBeenCalled();
  await user.click(dialog.getByRole('button', { name: 'Подтвердить откат' }));
  const error = await dialog.findByRole('alert');
  expect(error).toHaveTextContent('main.tex — изменён после правок');
  expect(error).toHaveTextContent('old.png — путь уже занят');
  expect(post).toHaveBeenCalledTimes(1);
});

test('после отката обновляет дерево даже без событий о файлах', async () => {
  openProject();
  server.use(
    http.post('/api/v1/changesets/:cid/revert', () => {
      mockState.current.projects.get(demoId)?.files.delete('main.tex');
      return HttpResponse.json(
        { ...changes.changeset, author: 'user', reverts_id: id },
        { status: 201 },
      );
    }),
  );
  expect(await screen.findByRole('button', { name: 'Открыть main.tex' })).toBeInTheDocument();
  const { user, dialog } = await confirmRevert();
  await user.click(dialog.getByRole('button', { name: 'Подтвердить откат' }));
  expect(await dialog.findByRole('status')).toHaveTextContent('Правки отменены.');
  await user.click(dialog.getByRole('button', { name: 'Закрыть' }));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Открыть main.tex' })).not.toBeInTheDocument(),
  );
  expect(screen.getByText('Правки отменены.')).toBeVisible();
});

test('пока агент работает, откат недоступен и объясняет почему', async () => {
  const runId = '00000000-0000-4000-8000-000000000051';
  let running = false;
  openProject();
  const post = vi.fn(() => HttpResponse.json(changes.changeset, { status: 201 }));
  server.use(
    http.post('/api/v1/changesets/:cid/revert', post),
    // Снимок переписки согласован с событиями: опрос не снимет блокировку раньше времени.
    http.get('/api/v1/projects/:pid/messages', () =>
      HttpResponse.json({
        items: [
          {
            id,
            role: 'assistant',
            run_id: null,
            status: 'done',
            seq: 0,
            created_at: timestamp,
            parts: [{ type: 'changeset', changeset_id: id }],
          },
        ],
        active_run: running
          ? {
              id: runId,
              status: 'running',
              message_id: '00000000-0000-4000-8000-000000000052',
              changeset_id: '00000000-0000-4000-8000-000000000053',
              error: null,
              created_at: timestamp,
              finished_at: null,
            }
          : null,
        has_more: false,
      }),
    ),
  );
  await screen.findByText('Обновления подключены');
  const { dialog } = await confirmRevert();
  running = true;
  await act(() => emitMockEvent(demoId, { event: 'project.locked', data: { run_id: runId } }));
  // Событие идёт через поток асинхронно: ждём, пока окно узнает о блокировке.
  expect(
    await dialog.findByText('Отменить правки можно, когда агент закончит работу.'),
  ).toBeVisible();
  expect(dialog.getByRole('button', { name: 'Подтвердить откат' })).toBeDisabled();
  running = false;
  await act(() => emitMockEvent(demoId, { event: 'project.unlocked', data: { run_id: runId } }));
  await waitFor(() =>
    expect(dialog.getByRole('button', { name: 'Подтвердить откат' })).toBeEnabled(),
  );
  expect(post).not.toHaveBeenCalled();
});
