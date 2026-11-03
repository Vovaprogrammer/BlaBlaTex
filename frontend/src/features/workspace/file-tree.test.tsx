import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { demoId, mockState, newFile } from '@/mocks/data';
import { invalid } from '@/mocks/responses';
import { buildFileTree } from './file-tree-data';

const path = `/projects/${demoId}`;
async function start() {
  renderApp(path);
  await screen.findByRole('tree', { name: 'Дерево файлов проекта' });
}
async function menu(file: string, action: string) {
  fireEvent.keyDown(await screen.findByRole('button', { name: `Действия для ${file}` }), {
    key: 'Enter',
  });
  await userEvent.setup().click(await screen.findByRole('menuitem', { name: action }));
  return screen.findByRole('dialog');
}
async function submit(dialog: HTMLElement, value: string, action: string) {
  fireEvent.change(within(dialog).getByRole('textbox'), { target: { value } });
  await userEvent.setup().click(within(dialog).getByRole('button', { name: action }));
}

test('плоский список превращается в дерево, автоматически созданные файлы защищают родителя', () => {
  const nested = newFile('chapters/auto.tex', '', 'generated').info;
  const nodes = buildFileTree([newFile('main.tex').info, nested]);
  expect(nodes.find((node) => node.id === 'chapters')).toMatchObject({
    protected: true,
    children: [{ id: 'chapters/auto.tex', protected: true }],
  });
  expect(nodes.at(-1)).toMatchObject({ id: 'materials', name: 'Материалы', section: true });
});

test('создание файла использует If-None-Match и обновляет дерево', async () => {
  const headers = vi.fn();
  server.use(
    http.put(/\/api\/v1\/projects\/.*\/files\/.+/, ({ request }) => {
      headers(request.headers.get('If-None-Match'));
    }),
  );
  await start();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Создать файл' }));
  await submit(await screen.findByRole('dialog'), 'заметки.tex', 'Создать файл');
  expect(await screen.findByRole('button', { name: 'Открыть заметки.tex' })).toBeInTheDocument();
  expect(headers).toHaveBeenCalledWith('*');
});

test('создание папки и переименование файла используют настоящий формат запросов', async () => {
  await start();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Создать папку' }));
  await submit(await screen.findByRole('dialog'), 'разделы', 'Создать папку');
  expect(await screen.findByRole('button', { name: 'Папка разделы' })).toBeInTheDocument();
  const dialog = await menu('main.tex', 'Переименовать');
  await submit(dialog, 'отчёт.tex', 'Переименовать');
  expect(await screen.findByRole('button', { name: 'Открыть отчёт.tex' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Открыть main.tex' })).not.toBeInTheDocument();
});

test('перенос в папку обновляет дерево и сохраняет содержимое', async () => {
  await start();
  const dialog = await menu('main.tex', 'Переместить');
  await submit(dialog, 'разделы/итог.tex', 'Переместить');
  expect(await screen.findByRole('button', { name: 'Открыть итог.tex' })).toBeInTheDocument();
  expect(mockState.current.projects.get(demoId)?.files.get('разделы/итог.tex')?.text).toContain(
    'documentclass',
  );
});

test('удаление требует подтверждения, отмена не удаляет файл', async () => {
  await start();
  let dialog = await menu('main.tex', 'Удалить');
  await userEvent.setup().click(within(dialog).getByRole('button', { name: 'Отменить' }));
  expect(screen.getByRole('button', { name: 'Открыть main.tex' })).toBeInTheDocument();
  dialog = await menu('main.tex', 'Удалить');
  await userEvent.setup().click(within(dialog).getByRole('button', { name: 'Удалить' }));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Открыть main.tex' })).not.toBeInTheDocument(),
  );
});

test('meta.tex отмечен как автоматический и не разрешает опасные действия', async () => {
  await start();
  expect(screen.getByText('Создаётся автоматически, только чтение')).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole('button', { name: 'Действия для meta.tex' }), {
    key: 'Enter',
  });
  await screen.findByRole('menuitem', { name: 'Переименовать' });
  for (const action of ['Переименовать', 'Переместить', 'Удалить'])
    expect(screen.getByRole('menuitem', { name: action })).toHaveAttribute('data-disabled');
});

test('ошибка пути от сервера показывается в форме без потери имени', async () => {
  server.use(
    http.post('/api/v1/projects/:pid/folders', () =>
      invalid('path', 'Имя не может начинаться с точки'),
    ),
  );
  await start();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Создать папку' }));
  const dialog = await screen.findByRole('dialog');
  await submit(dialog, '.hidden', 'Создать папку');
  await waitFor(() =>
    expect(within(dialog).getByRole('textbox')).toHaveAccessibleDescription(
      'Имя не может начинаться с точки',
    ),
  );
  expect(within(dialog).getByRole('textbox')).toHaveValue('.hidden');
});

test('создание существующего файла не перезаписывает содержимое', async () => {
  await start();
  const oldText = mockState.current.projects.get(demoId)?.files.get('main.tex')?.text;
  await userEvent.setup().click(screen.getByRole('button', { name: 'Создать файл' }));
  const dialog = await screen.findByRole('dialog');
  await submit(dialog, 'main.tex', 'Создать файл');
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Файл уже существует');
  expect(mockState.current.projects.get(demoId)?.files.get('main.tex')?.text).toBe(oldText);
});
