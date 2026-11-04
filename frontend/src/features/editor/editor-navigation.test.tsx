import { act, screen, waitFor } from '@testing-library/react';
import { EditorView } from '@codemirror/view';
import { expect, test } from 'vitest';
import { renderApp } from '@/test/render-app';
import { demoId, mockState } from '@/mocks/data';
import { tabsReducer, initialTabs } from '@/features/workspace/workspace-tabs';

test('ссылка открывает нужный исходник и ставит курсор в строку после загрузки', async () => {
  mockState.current.projects.get(demoId)!.files.get('main.tex')!.text = 'Первая\nВторая\nТретья';
  renderApp(`/projects/${demoId}?file=main.tex&line=2`);
  const element = await screen.findByRole('textbox', { name: 'Редактор main.tex' });
  const view = EditorView.findFromDOM(element)!;
  await waitFor(() => expect(view.state.selection.main.head).toBe(7));
  expect(element).toHaveFocus();
  await act(() =>
    view.dispatch({ changes: { from: 7, insert: 'Правка ' }, selection: { anchor: 14 } }),
  );
  expect(view.state.selection.main.head).toBe(14);
});

test('слишком большой номер ограничен последней строкой и работает для автоматического файла', async () => {
  const file = mockState.current.projects.get(demoId)!.files.get('meta.tex')!;
  file.text = 'Первая\nПоследняя';
  renderApp(`/projects/${demoId}?file=meta.tex&line=99999`);
  const element = await screen.findByRole('textbox', { name: 'Редактор meta.tex' });
  const view = EditorView.findFromDOM(element)!;
  await waitFor(() => expect(view.state.selection.main.head).toBe(7));
  expect(element).toHaveAttribute('contenteditable', 'false');
});

test('повторный запрос той же строки получает новый идентификатор перехода', () => {
  const first = tabsReducer(initialTabs, { kind: 'open', path: 'main.tex', line: 2 });
  const second = tabsReducer(first, { kind: 'open', path: 'main.tex', line: 2 });
  expect(second.paths).toEqual(['main.tex']);
  expect(second.target?.sequence).toBe(2);
  const moved = tabsReducer(second, {
    kind: 'change',
    change: { kind: 'move', from: 'main.tex', to: 'chapter.tex' },
  });
  expect(moved.target?.path).toBe('chapter.tex');
});
