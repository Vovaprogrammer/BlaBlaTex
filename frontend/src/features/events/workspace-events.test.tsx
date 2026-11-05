import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { http, HttpResponse } from 'msw';
import { expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { demoId, mockState, newFile, timestamp } from '@/mocks/data';
import { emitMockEvent } from '@/mocks/project-events';

const project = () => mockState.current.projects.get(demoId)!;
const file = () => project().files.get('main.tex')!;
async function open() {
  const app = renderApp(`/projects/${demoId}`);
  await screen.findByText('Обновления подключены');
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть main.tex' }));
  await screen.findByRole('textbox', { name: 'Редактор main.tex' });
  return app;
}
async function type(text: string) {
  const view = EditorView.findFromDOM(screen.getByRole('textbox', { name: 'Редактор main.tex' }))!;
  await act(() => {
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
  });
}
async function change(text: string) {
  file().text = text;
  file().info.version++;
  await act(() =>
    emitMockEvent(demoId, {
      event: 'file.changed',
      data: { path: 'main.tex', version: file().info.version, author: 'mcp', changeset_id: null },
    }),
  );
}

test('события переключают редактор в режим чтения, а кнопка баннера останавливает прогон', async () => {
  await open();
  const editor = screen.getByRole('textbox', { name: 'Редактор main.tex' });
  const runId = '00000000-0000-4000-8000-000000000012';
  let stopped: string | undefined;
  server.use(
    http.post('/api/v1/runs/:rid/cancel', ({ params }) => {
      stopped = String(params.rid);
      emitMockEvent(demoId, { event: 'project.unlocked', data: { run_id: runId } });
      return HttpResponse.json({ id: runId, status: 'cancelled' });
    }),
  );
  await act(() => emitMockEvent(demoId, { event: 'project.locked', data: { run_id: runId } }));
  const banner = within(await screen.findByRole('region', { name: 'Блокировка редактора' }));
  expect(editor).toHaveAttribute('aria-readonly', 'true');
  await userEvent.setup().click(banner.getByRole('button', { name: 'Остановить' }));
  await waitFor(() => expect(editor).toHaveAttribute('aria-readonly', 'false'));
  expect(stopped).toBe(runId);
});

test('события обновляют текст, дерево и вкладку при внешнем переносе', async () => {
  await open();
  await change('Внешняя правка');
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
      'Внешняя правка',
    ),
  );
  project().files.set('new.tex', newFile('new.tex', 'Новый файл'));
  await act(() =>
    emitMockEvent(demoId, {
      event: 'file.changed',
      data: { path: 'new.tex', version: 1, author: 'ai', changeset_id: null },
    }),
  );
  expect(await screen.findByRole('button', { name: 'Открыть new.tex' })).toBeInTheDocument();
  const moved = file();
  project().files.delete('main.tex');
  moved.info.path = 'renamed.tex';
  project().files.set('renamed.tex', moved);
  await act(() =>
    emitMockEvent(demoId, {
      event: 'file.moved',
      data: { from: 'main.tex', to: 'renamed.tex', changeset_id: null },
    }),
  );
  expect(await screen.findByRole('textbox', { name: 'Редактор renamed.tex' })).toHaveTextContent(
    'Внешняя правка',
  );
  expect(screen.getByRole('tab', { name: 'renamed.tex' })).toHaveAttribute('aria-selected', 'true');
  project().files.delete('renamed.tex');
  await act(() =>
    emitMockEvent(demoId, {
      event: 'file.deleted',
      data: { path: 'renamed.tex', changeset_id: null },
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole('tab', { name: 'renamed.tex' })).not.toBeInTheDocument(),
  );
});

test('внешняя правка открывает сравнение до PUT и сохраняет выбор пользователя', async () => {
  const puts = vi.fn();
  server.use(
    http.put(/\/files\/main.tex$/, () => {
      puts();
    }),
  );
  await open();
  await type('Мой черновик');
  await change('Версия другого клиента');
  const dialog = await screen.findByRole('dialog', { name: 'Файл изменился' });
  const mine = within(dialog).getByRole('button', { name: 'Оставить мою' });
  await waitFor(() => expect(mine).toBeEnabled());
  expect(puts).not.toHaveBeenCalled();
  expect(within(dialog).getByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
    'Мой черновик',
  );
  await userEvent.setup().click(mine);
  await waitFor(() => expect(file().text).toBe('Мой черновик'));
  await screen.findByText('Все изменения сохранены');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('внешнее удаление оставляет вкладку с моим текстом и запрещает автозапись', async () => {
  const puts = vi.fn();
  server.use(
    http.put(/\/files\/main.tex$/, () => {
      puts();
    }),
  );
  await open();
  await type('Несохранённый текст');
  project().files.delete('main.tex');
  await act(() =>
    emitMockEvent(demoId, {
      event: 'file.deleted',
      data: { path: 'main.tex', changeset_id: null },
    }),
  );
  await screen.findByText('Файл недоступен. Ваш текст остался в черновике');
  expect(screen.getByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
    'Несохранённый текст',
  );
  expect(screen.getByRole('button', { name: 'Скопировать мой текст' })).toBeInTheDocument();
  expect(puts).not.toHaveBeenCalled();
});

test('сборка другого клиента появляется в интерфейсе по событию', async () => {
  await open();
  const id = crypto.randomUUID();
  mockState.current.builds.set(id, {
    id,
    project_id: demoId,
    status: 'ok',
    engine: 'xelatex',
    pages: 3,
    duration_ms: 100,
    warnings_count: 0,
    errors: [],
    has_pdf: true,
    created_at: timestamp,
  });
  await act(() =>
    emitMockEvent(demoId, {
      event: 'build.finished',
      data: { build_id: id, status: 'ok', pages: 3, errors_count: 0 },
    }),
  );
  expect(await screen.findByText('Документ собран')).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Скачать PDF' })).toBeEnabled());
});

test('внешний перенос сохраняет черновик по старому пути и показывает новый файл', async () => {
  await open();
  await type('Несохранённый текст до переноса');
  const moved = file();
  project().files.delete('main.tex');
  moved.info.path = 'moved.tex';
  project().files.set('moved.tex', moved);
  await act(() =>
    emitMockEvent(demoId, {
      event: 'file.moved',
      data: { from: 'main.tex', to: 'moved.tex', changeset_id: null },
    }),
  );
  await screen.findByText('Файл недоступен. Ваш текст остался в черновике');
  expect(screen.getByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
    'Несохранённый текст до переноса',
  );
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть moved.tex' }));
  expect(await screen.findByRole('textbox', { name: 'Редактор moved.tex' })).not.toHaveTextContent(
    'Несохранённый текст до переноса',
  );
  expect(screen.getByRole('tab', { name: 'main.tex' })).toBeInTheDocument();
});

test('после обрыва свежий снимок исправляет пропуск события', async () => {
  let requests = 0;
  let release!: () => void;
  const resumed = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.get('/api/v1/projects/:pid/events', async () => {
      requests++;
      if (requests === 1)
        return HttpResponse.json(
          { error: { code: 'internal', message: 'Временный обрыв', details: {} } },
          { status: 500 },
        );
      await resumed;
      file().text = 'Изменено во время обрыва';
      file().info.version = 10;
    }),
  );
  renderApp(`/projects/${demoId}`);
  await screen.findByText('Временный обрыв');
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть main.tex' }));
  const editor = await screen.findByRole('textbox', { name: 'Редактор main.tex' });
  expect(editor).not.toHaveTextContent('Изменено во время обрыва');
  await act(() => release());
  await waitFor(
    () =>
      expect(screen.getByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
        'Изменено во время обрыва',
      ),
    { timeout: 5000 },
  );
  expect(requests).toBe(2);
});
