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
import { emitMockEvent } from '@/mocks/project-events';
import { projectsKey } from './project-queries';
import { workspaceKeys } from '@/features/workspace/workspace-queries';
import type { components } from '@/api/schema';

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

test('правка варианта обновляет проект, карточку и открытый meta.tex без событий', async () => {
  server.use(
    http.get('/api/v1/projects/:pid/events', () => failure(403, 'forbidden', 'Нет событий')),
  );
  const { client } = renderApp(`/projects/${demoId}`);
  const user = userEvent.setup();
  await screen.findByText('Автообновления недоступны');
  await user.click(await screen.findByRole('button', { name: 'Открыть meta.tex' }));
  const meta = await screen.findByRole('textbox', { name: 'Редактор meta.tex' });
  await chooseAction('Данные работы');
  const dialog = within(await screen.findByRole('dialog', { name: 'Данные работы' }));
  const variant = await dialog.findByRole('combobox', { name: 'Вариант' });
  expect(variant).toHaveValue('А');
  await user.selectOptions(variant, 'Б');
  await user.click(dialog.getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() => expect(meta).toHaveTextContent('Вариант: Б'));
  expect(client.getQueryData(workspaceKeys.project(demoId))).toMatchObject({
    fields: { variant: 'Б', lab_number: 1, report_title: 'Учебный отчёт' },
  });
  expect(
    client.getQueryData<components['schemas']['ProjectList']>(projectsKey)?.items[0],
  ).toMatchObject({
    id: demoId,
    title: 'Учебный отчёт',
    fields: { variant: 'Б' },
  });
});

test.each([
  [
    422,
    'validation_error',
    'Этот вариант уже занят',
    { errors: [{ loc: ['body', 'fields', 'variant'], message: 'Этот вариант уже занят' }] },
  ],
  [423, 'project_locked', 'Дождитесь ответа помощника', {}],
] as const)(
  'ответ %s при сохранении оставляет диалог и введённые данные',
  async (status, code, message, details) => {
    server.use(http.patch('/api/v1/projects/:pid', () => failure(status, code, message, details)));
    renderApp('/projects');
    await chooseAction('Данные работы');
    const dialog = within(await screen.findByRole('dialog', { name: 'Данные работы' }));
    const user = userEvent.setup();
    const variant = await dialog.findByRole('combobox', { name: 'Вариант' });
    await user.selectOptions(variant, 'Б');
    await user.click(dialog.getByRole('button', { name: 'Сохранить изменения' }));
    expect(await dialog.findByRole('alert')).toHaveTextContent(message);
    expect(variant).toHaveValue('Б');
    if (status === 422) {
      expect(variant).toHaveAccessibleDescription(expect.stringContaining(message));
      await waitFor(() => expect(variant).toHaveFocus());
    }
  },
);

test('устаревшая форма сохраняет ввод и не отправляет PATCH поверх новых данных', async () => {
  const patch = vi.fn(() => new HttpResponse(null, { status: 500 }));
  server.use(http.patch('/api/v1/projects/:pid', patch));
  renderApp('/projects');
  await chooseAction('Данные работы');
  const dialog = within(await screen.findByRole('dialog', { name: 'Данные работы' }));
  const user = userEvent.setup();
  const variant = await dialog.findByRole('combobox', { name: 'Вариант' });
  const project = mockState.current.projects.get(demoId)!.project;
  project.fields = { ...project.fields, lab_number: 2 };
  await user.selectOptions(variant, 'Б');
  await user.click(dialog.getByRole('button', { name: 'Сохранить изменения' }));
  expect(await dialog.findByRole('alert')).toHaveTextContent('Данные работы уже изменились');
  expect(variant).toHaveValue('Б');
  expect(patch).not.toHaveBeenCalled();
});

test('во время известной блокировки пункт «Данные работы» недоступен', async () => {
  renderApp(`/projects/${demoId}`);
  await screen.findByText('Обновления подключены');
  await act(() =>
    emitMockEvent(demoId, {
      event: 'project.locked',
      data: { run_id: '00000000-0000-4000-8000-000000000012' },
    }),
  );
  await screen.findByRole('region', { name: 'Блокировка файлов' });
  fireEvent.keyDown(await screen.findByRole('button', { name: /Действия с проектом/ }), {
    key: 'Enter',
  });
  expect(await screen.findByRole('menuitem', { name: 'Данные работы' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
});

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
