import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { demoId, mockState, type Schemas } from '@/mocks/data';
import { failure } from '@/mocks/responses';
import { emitMockEvent } from '@/mocks/project-events';
import { buildKeys } from './pdf-queries';

function history(success = true) {
  const old: Schemas['BuildOut'] = {
    id: 'previous',
    project_id: demoId,
    status: 'ok',
    has_pdf: true,
    engine: 'xelatex',
    pages: 3,
    errors: [],
    warnings_count: 0,
    duration_ms: 100,
    created_at: '2026-01-01T00:00:00Z',
  };
  const failed: Schemas['BuildOut'] = {
    ...old,
    id: 'failed',
    status: 'error',
    has_pdf: false,
    pages: null,
    created_at: '2026-01-02T00:00:00Z',
    errors: [
      {
        file: 'main.tex',
        line: 3,
        message: 'Неизвестная команда',
        severity: 'error',
        context: '3: \\badcommand',
      },
    ],
  };
  if (success) mockState.current.builds.set(old.id, old);
  mockState.current.builds.set(failed.id, failed);
  return { old, failed };
}

test('при повторном открытии после ошибки восстанавливается последний успешный PDF', async () => {
  const { old } = history();
  const first = renderApp(`/projects/${demoId}`);
  await screen.findByText('Показан PDF предыдущей сборки.');
  first.unmount();
  first.client.clear();
  const reopened = renderApp(`/projects/${demoId}`);
  await screen.findByText('Не удалось собрать документ');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Скачать PDF' })).toBeEnabled());
  expect(reopened.client.getQueryData(buildKeys.successful(demoId))).toMatchObject({ id: old.id });
  expect(screen.getByText(/Неизвестная команда/)).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole('spinbutton', { name: 'Номер страницы PDF' })).toHaveAttribute(
      'max',
      '3',
    ),
  );
});

test('404 последней успешной сборки оставляет ошибки и пустой просмотрщик', async () => {
  history(false);
  await open();
  await screen.findByText('Не удалось собрать документ');
  expect(screen.getByRole('button', { name: 'Скачать PDF' })).toBeDisabled();
  expect(screen.queryByText('Показан PDF предыдущей сборки.')).not.toBeInTheDocument();
  expect(
    screen.getByText('PDF пока нет. Здесь появится результат сборки документа.'),
  ).toBeInTheDocument();
});

test('сбой поиска предыдущего PDF повторяется отдельно от статуса последней сборки', async () => {
  history();
  let fail = true;
  server.use(
    http.get('/api/v1/projects/:pid/builds/latest', ({ request }) => {
      if (fail && new URL(request.url).searchParams.get('status') === 'ok')
        return failure(500, 'internal', 'Предыдущий PDF временно недоступен');
    }),
  );
  await open();
  await screen.findByText('Предыдущий PDF временно недоступен');
  fail = false;
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: 'Повторить поиск предыдущего PDF' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Скачать PDF' })).toBeEnabled());
  expect(screen.getByText('Не удалось собрать документ')).toBeInTheDocument();
});

test('событие обновляет успешный PDF, даже если последняя сборка всё ещё с ошибкой', async () => {
  history(false);
  const { client } = renderApp(`/projects/${demoId}`);
  await screen.findByText('Не удалось собрать документ');
  const { old } = history();
  await act(() =>
    emitMockEvent(demoId, {
      event: 'build.finished',
      data: { build_id: old.id, status: 'ok', pages: 3, errors_count: 0 },
    }),
  );
  await waitFor(() => expect(screen.getByRole('button', { name: 'Скачать PDF' })).toBeEnabled());
  expect(client.getQueryData(buildKeys.successful(demoId))).toMatchObject({ id: old.id });
});

async function open() {
  renderApp(`/projects/${demoId}`);
  const button = await screen.findByRole('button', { name: 'Собрать PDF' });
  await waitFor(() => expect(button).toBeEnabled());
  return userEvent.setup();
}
test('фоновая сборка проходит очередь, показывает PDF и включает скачивание', async () => {
  const user = await open();
  expect(screen.getByRole('button', { name: 'Скачать PDF' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Собрать PDF' }));
  expect(await screen.findByText('Собираем документ…')).toBeInTheDocument();
  await screen.findByText('Документ собран', {}, { timeout: 6000 });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Скачать PDF' })).toBeEnabled());
  expect(screen.getByRole('spinbutton', { name: 'Номер страницы PDF' })).toHaveAttribute(
    'max',
    '3',
  );
});
test('сборка сначала сохраняет введённую правку, не ожидая debounce', async () => {
  const user = await open();
  await user.click(screen.getByRole('button', { name: 'Открыть main.tex' }));
  const editor = EditorView.findFromDOM(
    await screen.findByRole('textbox', { name: 'Редактор main.tex' }),
  )!;
  let textAtBuild = '';
  server.use(
    http.post(/\/projects\/[^/]+\/builds$/, () => {
      textAtBuild = mockState.current.projects.get(demoId)!.files.get('main.tex')!.text!;
    }),
  );
  await act(() =>
    editor.dispatch({
      changes: { from: 0, to: editor.state.doc.length, insert: 'Правка перед сборкой' },
    }),
  );
  await user.click(screen.getByRole('button', { name: 'Собрать PDF' }));
  await waitFor(() => expect(textAtBuild).toBe('Правка перед сборкой'));
});
test('ошибка опроса показывается и повтор возобновляет ожидание сборки', async () => {
  const user = await open();
  server.use(
    http.get(/\/builds\/[^/]+$/, () => failure(500, 'internal', 'Состояние временно недоступно')),
  );
  await user.click(screen.getByRole('button', { name: 'Собрать PDF' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Состояние временно недоступно');
  server.resetHandlers();
  await user.click(screen.getByRole('button', { name: 'Обновить состояние сборки' }));
  await screen.findByText('Документ собран', {}, { timeout: 6000 });
});
test('неудачная новая сборка сохраняет прежний PDF', async () => {
  const old: Schemas['BuildOut'] = {
    id: 'old',
    project_id: demoId,
    status: 'ok',
    has_pdf: true,
    engine: 'xelatex',
    pages: 3,
    errors: [],
    warnings_count: 0,
    duration_ms: 1,
    created_at: '2026-01-01T00:00:00Z',
  };
  mockState.current.builds.set(old.id, old);
  const user = await open();
  await screen.findByRole('spinbutton', { name: 'Номер страницы PDF' });
  server.use(
    http.post(/\/projects\/[^/]+\/builds$/, () => {
      const failed: Schemas['BuildOut'] = { ...old, id: 'failed', status: 'error', has_pdf: false };
      mockState.current.builds.set(failed.id, failed);
      return HttpResponse.json(failed, { status: 202 });
    }),
  );
  await user.click(screen.getByRole('button', { name: 'Собрать PDF' }));
  await screen.findByText('Не удалось собрать документ');
  expect(screen.getByText('Показан PDF предыдущей сборки.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Скачать PDF' })).toBeEnabled();
});

test('обновление замечает новую сборку другого клиента после собственной сборки', async () => {
  const user = await open();
  await user.click(screen.getByRole('button', { name: 'Собрать PDF' }));
  await screen.findByText('Документ собран', {}, { timeout: 6000 });
  const previous = [...mockState.current.builds.values()].at(-1)!;
  mockState.current.builds.set('external', {
    ...previous,
    id: 'external',
    status: 'timeout',
    has_pdf: false,
  });
  await user.click(screen.getByRole('button', { name: 'Обновить состояние сборки' }));
  expect(await screen.findByText('Время сборки истекло')).toBeInTheDocument();
});

test('ошибка сохранения запрещает сборку старого текста', async () => {
  const user = await open();
  await user.click(screen.getByRole('button', { name: 'Открыть main.tex' }));
  const editor = EditorView.findFromDOM(
    await screen.findByRole('textbox', { name: 'Редактор main.tex' }),
  )!;
  let starts = 0;
  server.use(
    http.put(/\/files\/main.tex$/, () => failure(500, 'internal', 'Не удалось сохранить файл')),
    http.post(/\/projects\/[^/]+\/builds$/, () => {
      starts++;
    }),
  );
  await act(() =>
    editor.dispatch({
      changes: { from: 0, to: editor.state.doc.length, insert: 'Несохранённый текст' },
    }),
  );
  await user.click(screen.getByRole('button', { name: 'Собрать PDF' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Собрать PDF' })).toBeDisabled());
  expect(starts).toBe(0);
  expect(editor.state.doc.toString()).toBe('Несохранённый текст');
});
