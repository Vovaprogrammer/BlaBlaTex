import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { http } from 'msw';
import { expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { demoId, mockState } from '@/mocks/data';
import { failure } from '@/mocks/responses';

// Холодная загрузка редактора и настоящий debounce входят в бюджет сценария.
vi.setConfig({ testTimeout: 10_000 });

async function open() {
  const app = renderApp(`/projects/${demoId}`);
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть main.tex' }));
  await screen.findByRole('textbox', { name: 'Редактор main.tex' });
  return app;
}
async function type(text: string) {
  const element = screen.getByRole('textbox', { name: 'Редактор main.tex' });
  const view = EditorView.findFromDOM(element)!;
  await act(() => {
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
  });
}
const file = () => mockState.current.projects.get(demoId)!.files.get('main.tex')!;

test('редактор записывает текст через API с If-Match и обновляет версию', async () => {
  const versions: (string | null)[] = [];
  server.use(
    http.put(/\/files\/main.tex$/, ({ request }) => {
      versions.push(request.headers.get('If-Match'));
    }),
  );
  await open();
  await type('Сохранённая правка');
  await waitFor(() => expect(file().text).toBe('Сохранённая правка'), { timeout: 4000 });
  expect(versions).toEqual(['"1"']);
  expect(await screen.findByText('Все изменения сохранены')).toBeInTheDocument();
  expect(file().info.version).toBe(2);
});

test('реальный сценарий 412 сравнивает версии и сохраняет мой текст по новой версии', async () => {
  const versions: (string | null)[] = [];
  server.use(
    http.put(/\/files\/main.tex$/, ({ request }) => {
      versions.push(request.headers.get('If-Match'));
    }),
  );
  await open();
  file().text = 'Серверная правка';
  file().info.version = 7;
  await type('Моя правка');
  const dialog = await screen.findByRole('dialog', { name: 'Файл изменился' });
  await waitFor(() =>
    expect(within(dialog).getByRole('button', { name: 'Оставить мою' })).toBeEnabled(),
  );
  expect(within(dialog).getByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
    'Моя правка',
  );
  await userEvent.setup().click(within(dialog).getByRole('button', { name: 'Оставить мою' }));
  await waitFor(() => expect(file().text).toBe('Моя правка'));
  expect(versions).toEqual(['"1"', '"7"']);
});

test('выбор сервера оставляет возможность вернуть свой черновик', async () => {
  await open();
  file().text = 'Текст сервера';
  file().info.version = 2;
  await type('Мой черновик');
  const dialog = await screen.findByRole('dialog', { name: 'Файл изменился' });
  await waitFor(() =>
    expect(within(dialog).getByRole('button', { name: 'Взять версию с сервера' })).toBeEnabled(),
  );
  await userEvent
    .setup()
    .click(within(dialog).getByRole('button', { name: 'Взять версию с сервера' }));
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
      'Текст сервера',
    ),
  );
  await userEvent.setup().click(screen.getByRole('button', { name: 'Вернуть мой черновик' }));
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
      'Мой черновик',
    ),
  );
});

test('ошибка не теряет текст при закрытии вкладки; повтор сохраняет и снимает предупреждение', async () => {
  server.use(
    http.put(/\/files\/main.tex$/, () => failure(500, 'internal', 'Сохранение недоступно')),
  );
  await open();
  await type('Не терять этот текст');
  expect(await screen.findByRole('alert')).toHaveTextContent('Сохранение недоступно');
  const before = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(before);
  expect(before.defaultPrevented).toBe(true);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Закрыть main.tex' }));
  fireEvent.keyDown(screen.getByRole('button', { name: 'Несохранённых файлов: 1' }), {
    key: 'Enter',
  });
  await userEvent.setup().click(await screen.findByRole('menuitem', { name: 'main.tex' }));
  expect(await screen.findByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
    'Не терять этот текст',
  );
  server.resetHandlers();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Повторить' }));
  await screen.findByText('Все изменения сохранены');
  const after = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(after);
  expect(after.defaultPrevented).toBe(false);
});

test('чужая сессия не получает черновик предыдущего пользователя', async () => {
  const { client } = await open();
  await type('Приватный черновик');
  await act(() =>
    client.setQueryData(['session'], {
      user: {
        id: 'another-user',
        email: 'other@example.com',
        role: 'student',
        created_at: '2026-01-01',
      },
      profile: {},
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: 'Несохранённых файлов: 1' }),
    ).not.toBeInTheDocument(),
  );
  expect(screen.queryByText('Приватный черновик')).not.toBeInTheDocument();
});

test('нельзя переименовать файл с несохранённой правкой', async () => {
  await open();
  await type('Черновик');
  fireEvent.keyDown(screen.getByRole('button', { name: 'Действия для main.tex' }), {
    key: 'Enter',
  });
  await userEvent.setup().click(await screen.findByRole('menuitem', { name: 'Переименовать' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'other.tex' } });
  await userEvent.setup().click(within(dialog).getByRole('button', { name: 'Переименовать' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Сначала сохраните изменения');
  expect(file().text).not.toBe('Черновик');
});
