import { act, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { EditorView } from '@codemirror/view';
import { ThemeProvider } from '@/app/theme-provider';
import { SourceEditor } from './source-editor';

test('редактор показывает исходник и передаёт изменения текста', async () => {
  let editor: EditorView | undefined;
  const change = vi.fn();
  render(
    <ThemeProvider>
      <SourceEditor
        path="main.tex"
        value={'\\section{Цель}\nТекст'}
        onChange={change}
        onCreate={(view) => {
          editor = view;
        }}
      />
    </ThemeProvider>,
  );
  expect(await screen.findByRole('textbox', { name: 'Редактор main.tex' })).toHaveTextContent(
    'section',
  );
  await act(() => {
    editor!.dispatch({ changes: { from: editor!.state.doc.length, insert: '\nПравка' } });
  });
  expect(change).toHaveBeenCalledWith('\\section{Цель}\nТекст\nПравка');
});

test('автоматический файл не допускает пользовательского редактирования', async () => {
  render(
    <ThemeProvider>
      <SourceEditor path="meta.tex" value="% Метаданные" readOnly onChange={vi.fn()} />
    </ThemeProvider>,
  );
  const content = await screen.findByRole('textbox', { name: 'Редактор meta.tex' });
  expect(content).toHaveAttribute('contenteditable', 'false');
  expect(content).toHaveAttribute('aria-readonly', 'true');
});
