import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { demoId, mockState } from '@/mocks/data';
import { initialTabs, tabsReducer } from './workspace-tabs';

test('вкладки не дублируются, PDF остаётся после закрытия последнего файла', () => {
  let state = tabsReducer(initialTabs, { kind: 'open', path: 'main.tex' });
  state = tabsReducer(state, { kind: 'open', path: 'main.tex' });
  expect(state.paths).toEqual(['main.tex']);
  expect(tabsReducer(state, { kind: 'close', path: 'main.tex' })).toEqual(initialTabs);
});

test('вкладки вложенных файлов следуют за переносом и закрываются при удалении папки', () => {
  const state = { paths: ['chapters/a.tex', 'main.tex'], active: 'chapters/a.tex' };
  const moved = tabsReducer(state, {
    kind: 'change',
    change: { kind: 'move', from: 'chapters', to: 'разделы' },
  });
  expect(moved).toEqual({ paths: ['разделы/a.tex', 'main.tex'], active: 'разделы/a.tex' });
  expect(
    tabsReducer(moved, { kind: 'change', change: { kind: 'delete', path: 'разделы' } }),
  ).toEqual({ paths: ['main.tex'], active: null });
});

test('файл открывается справа для чтения, PDF не имеет кнопки закрытия', async () => {
  renderApp(`/projects/${demoId}`);
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть main.tex' }));
  expect(await screen.findByText(/documentclass/)).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: 'main.tex' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('textbox', { name: 'Редактор main.tex' })).toHaveAttribute(
    'aria-readonly',
    'false',
  );
  expect(screen.queryByRole('button', { name: 'Закрыть PDF' })).not.toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Открыть main.tex' }));
  expect(screen.getAllByRole('tab', { name: 'main.tex' })).toHaveLength(1);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Закрыть main.tex' }));
  expect(screen.getByRole('tab', { name: 'PDF' })).toHaveAttribute('aria-selected', 'true');
});

test('автоматический файл открывается с отметкой только для чтения', async () => {
  renderApp(`/projects/${demoId}`);
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть meta.tex' }));
  const panel = screen.getByRole('tabpanel', { name: 'meta.tex' });
  expect(within(panel).getByText('Создаётся автоматически, только чтение')).toBeInTheDocument();
  expect(await within(panel).findByText('% Создаётся автоматически.')).toBeInTheDocument();
});

test('переименование открытого файла обновляет вкладку и повторно читает новый путь', async () => {
  renderApp(`/projects/${demoId}`);
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть main.tex' }));
  await screen.findByText(/documentclass/);
  fireEvent.keyDown(screen.getByRole('button', { name: 'Действия для main.tex' }), {
    key: 'Enter',
  });
  await userEvent.setup().click(await screen.findByRole('menuitem', { name: 'Переименовать' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'новый.tex' } });
  await userEvent.setup().click(within(dialog).getByRole('button', { name: 'Переименовать' }));
  expect(await screen.findByRole('tab', { name: 'новый.tex' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  expect(await screen.findByText(/documentclass/)).toBeInTheDocument();
});

test('обновление дерева закрывает вкладку удалённого вне интерфейса файла', async () => {
  const { client } = renderApp(`/projects/${demoId}`);
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть main.tex' }));
  await screen.findByText(/documentclass/);
  mockState.current.projects.get(demoId)!.files.delete('main.tex');
  await act(() => client.invalidateQueries({ queryKey: ['projects', demoId, 'tree'] }));
  await waitFor(() =>
    expect(screen.queryByRole('tab', { name: 'main.tex' })).not.toBeInTheDocument(),
  );
  expect(screen.getByRole('tab', { name: 'PDF' })).toHaveAttribute('aria-selected', 'true');
});

test('клавиатура переключает вкладки и закрывает файл без удаления PDF', async () => {
  renderApp(`/projects/${demoId}`);
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть main.tex' }));
  await screen.findByText(/documentclass/);
  fireEvent.keyDown(screen.getByRole('tab', { name: 'main.tex' }), { key: 'Home' });
  expect(screen.getByRole('tab', { name: 'PDF' })).toHaveAttribute('aria-selected', 'true');
  fireEvent.keyDown(screen.getByRole('tab', { name: 'PDF' }), { key: 'ArrowRight' });
  expect(screen.getByRole('tab', { name: 'main.tex' })).toHaveAttribute('aria-selected', 'true');
  fireEvent.keyDown(screen.getByRole('tab', { name: 'main.tex' }), { key: 'Delete' });
  expect(screen.queryByRole('tab', { name: 'main.tex' })).not.toBeInTheDocument();
  expect(screen.getByRole('tab', { name: 'PDF' })).toBeInTheDocument();
});

test('созданный на мобильном экране файл остаётся открытым после обновления дерева', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
  try {
    renderApp(`/projects/${demoId}`);
    const panels = await screen.findByRole('tablist', { name: 'Панели рабочего окна' });
    await userEvent.setup().click(within(panels).getByRole('tab', { name: 'Файлы' }));
    await screen.findByRole('tree');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Создать файл' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'мобильный.tex' } });
    await userEvent.setup().click(within(dialog).getByRole('button', { name: 'Создать файл' }));
    expect(await screen.findByText('Файл пуст')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'мобильный.tex' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  } finally {
    vi.unstubAllGlobals();
  }
});
