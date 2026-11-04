import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { demoId, mockState, type Schemas } from '@/mocks/data';
import { failure } from '@/mocks/responses';

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
