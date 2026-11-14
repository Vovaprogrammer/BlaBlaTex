import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { http, HttpResponse } from 'msw';
import { toast } from 'sonner';
import { afterEach, expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { mockState, demoId } from '@/mocks/data';
import { server } from '@/test/server';
import { failure, invalid } from '@/mocks/responses';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function chooseAction(kind: string) {
  fireEvent.keyDown(await screen.findByRole('button', { name: /Действия с проектом/ }), {
    key: 'Enter',
  });
  await userEvent.setup().click(await screen.findByRole('menuitem', { name: kind }));
}

async function action(kind: 'Переименовать проект' | 'Удалить проект') {
  await chooseAction(kind);
  return screen.findByRole('dialog', { name: kind });
}

test('экспорт запрашивает исходники текущего проекта и сохраняет ZIP с именем из ответа', async () => {
  const filename = 'ЛР3_Иванов.zip';
  const createObjectURL = vi.fn(() => 'blob:test-archive');
  vi.stubGlobal(
    'URL',
    class extends URL {
      static override createObjectURL = createObjectURL;
      static override revokeObjectURL = vi.fn();
    },
  );
  const download = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    download(this.download, this.href);
  });
  const exportArchive = vi.fn<(request: Request) => Response>().mockReturnValue(
    new HttpResponse(new Uint8Array([0x50, 0x4b, 0x05, 0x06]), {
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': `attachment; filename="sources.zip"; filename*=UTF-8''${encodeURIComponent(filename)}`,
      },
    }),
  );
  server.use(http.get('/api/v1/projects/:id/export.zip', ({ request }) => exportArchive(request)));

  renderApp(`/projects/${demoId}`);
  await chooseAction('Скачать исходники ZIP');

  await waitFor(() => expect(download).toHaveBeenCalledWith(filename, 'blob:test-archive'));
  expect(createObjectURL).toHaveBeenCalledWith(
    expect.objectContaining({ type: 'application/zip' }),
  );
  expect(exportArchive).toHaveBeenCalledTimes(1);
  const url = new URL(exportArchive.mock.calls[0]![0].url);
  expect(url.pathname).toBe(`/api/v1/projects/${demoId}/export.zip`);
  expect(url.search).toBe('');
});

test('ошибка экспорта показывается сообщением сервера', async () => {
  const notify = vi.spyOn(toast, 'error').mockReturnValue('api-error');
  server.use(
    http.get('/api/v1/projects/:id/export.zip', () =>
      failure(500, 'internal', 'Не удалось подготовить архив проекта'),
    ),
  );
  renderApp('/projects');
  await chooseAction('Скачать исходники ZIP');
  await waitFor(() =>
    expect(notify).toHaveBeenCalledWith('Не удалось подготовить архив проекта', {
      id: 'api-error',
    }),
  );
});
test('переименование из рабочего окна обновляет выбор проекта и карточку списка', async () => {
  renderApp(`/projects/${demoId}`);
  const dialog = await action('Переименовать проект');
  const user = userEvent.setup();
  await user.clear(within(dialog).getByRole('textbox', { name: 'Название проекта' }));
  await user.type(
    within(dialog).getByRole('textbox', { name: 'Название проекта' }),
    'Новое название',
  );
  await user.click(within(dialog).getByRole('button', { name: 'Сохранить название' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(
    within(screen.getByRole('combobox', { name: 'Выбрать проект' })).getByRole('option', {
      selected: true,
    }),
  ).toHaveTextContent('Новое название');
  await user.click(screen.getByRole('link', { name: 'BlaBlaTex — на главную' }));
  expect(await screen.findByRole('heading', { name: 'Новое название' })).toBeInTheDocument();
});
test('удаление требует подтверждения, отмена сохраняет проект', async () => {
  renderApp('/projects');
  const user = userEvent.setup();
  let dialog = await action('Удалить проект');
  expect(mockState.current.projects.has(demoId)).toBe(true);
  await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));
  expect(mockState.current.projects.has(demoId)).toBe(true);
  dialog = await action('Удалить проект');
  await user.click(within(dialog).getByRole('button', { name: 'Удалить проект' }));
  expect(await screen.findByRole('heading', { name: 'Пока нет проектов' })).toBeInTheDocument();
  expect(mockState.current.projects.has(demoId)).toBe(false);
});
test('ошибка сервера при переименовании сохраняет ввод и показывается у поля', async () => {
  server.use(
    http.patch('/api/v1/projects/:id', () => invalid('title', 'Это название не подходит')),
  );
  renderApp('/projects');
  const dialog = await action('Переименовать проект');
  await userEvent.setup().click(within(dialog).getByRole('button', { name: 'Сохранить название' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Это название не подходит');
  expect(within(dialog).getByRole('textbox', { name: 'Название проекта' })).toHaveValue(
    mockState.current.projects.get(demoId)!.project.title,
  );
});
test('несохранённая правка запрещает удалить проект и остаётся в редакторе', async () => {
  server.use(
    http.put(/\/files\/main.tex$/, () => failure(500, 'internal', 'Сохранение недоступно')),
  );
  renderApp(`/projects/${demoId}`);
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть main.tex' }));
  const view = EditorView.findFromDOM(
    await screen.findByRole('textbox', { name: 'Редактор main.tex' }),
  )!;
  await act(() =>
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: 'Не терять' } }),
  );
  const dialog = await action('Удалить проект');
  expect(within(dialog).getByRole('button', { name: 'Удалить проект' })).toBeDisabled();
  expect(within(dialog).getByRole('alert')).toHaveTextContent('Сначала сохраните');
  expect(view.state.doc.toString()).toBe('Не терять');
  expect(mockState.current.projects.has(demoId)).toBe(true);
});

test('старый ответ списка не возвращает удалённый из рабочего окна проект', async () => {
  const original = mockState.current.projects.get(demoId)!.project;
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  let first = true;
  server.use(
    http.get('/api/v1/projects', async () => {
      if (!first) return;
      first = false;
      await delayed;
      return HttpResponse.json({ items: [original] });
    }),
  );
  renderApp(`/projects/${demoId}`);
  const dialog = await action('Удалить проект');
  await userEvent.setup().click(within(dialog).getByRole('button', { name: 'Удалить проект' }));
  await screen.findByRole('heading', { name: 'Ваши проекты' });
  release();
  expect(await screen.findByRole('heading', { name: 'Пока нет проектов' })).toBeInTheDocument();
});
