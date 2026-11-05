import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import type { components } from '@/api/schema';
import { demoId, timestamp } from '@/mocks/data';
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
