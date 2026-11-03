import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { WorkspaceLayout } from './workspace-layout';
import { readPanelLayout, savePanelLayout } from './workspace-preferences';
import { renderApp } from '@/test/render-app';
import { demoId } from '@/mocks/data';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.removeItem('bbt-workspace-panels');
});

test('повреждённые размеры и недоступное хранилище не мешают открыть панели', () => {
  localStorage.setItem('bbt-workspace-panels', '{bad');
  expect(readPanelLayout()).toEqual({ files: 20, chat: 44, document: 36 });
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  expect(readPanelLayout()).toEqual({ files: 20, chat: 44, document: 36 });
  expect(() => savePanelLayout({ files: 25, chat: 40, document: 35 })).not.toThrow();
});

test('размеры сохраняются и восстанавливаются без данных проекта', () => {
  savePanelLayout({ files: 25, chat: 40, document: 35 });
  expect(readPanelLayout()).toEqual({ files: 25, chat: 40, document: 35 });
});

test('на узком экране доступна одна панель с переключателями', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
  const change = vi.fn();
  render(
    <WorkspaceLayout
      files="Файловая панель"
      chat="Панель чата"
      document="Панель документа"
      section="chat"
      onSectionChange={change}
    />,
  );
  expect(screen.getByRole('tabpanel')).toHaveTextContent('Панель чата');
  expect(screen.queryByText('Файловая панель')).not.toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('tab', { name: 'Файлы' }));
  expect(change).toHaveBeenCalledWith('files');
});

test('рабочее окно показывает три панели и выбор текущего проекта', async () => {
  renderApp(`/projects/${demoId}`);
  expect(await screen.findByRole('combobox', { name: 'Выбрать проект' })).toHaveValue(demoId);
  expect(await screen.findByRole('region', { name: 'Чат с помощником' })).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Предпросмотр PDF' })).toBeInTheDocument();
  expect(screen.queryByRole('navigation', { name: 'Разделы приложения' })).not.toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Чаты' }));
  expect(screen.getByRole('button', { name: 'Чат проекта' })).toBeInTheDocument();
});
