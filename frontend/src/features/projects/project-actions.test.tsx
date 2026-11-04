import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import { renderApp } from '@/test/render-app';
import { mockState, demoId } from '@/mocks/data';
import { server } from '@/test/server';
import { failure, invalid } from '@/mocks/responses';

async function action(kind: 'Переименовать проект' | 'Удалить проект') {
  fireEvent.keyDown(await screen.findByRole('button', { name: /Действия с проектом/ }), {
    key: 'Enter',
  });
  await userEvent.setup().click(await screen.findByRole('menuitem', { name: kind }));
  return screen.findByRole('dialog', { name: kind });
}
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
