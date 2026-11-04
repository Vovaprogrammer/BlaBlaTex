import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { expect, test } from 'vitest';
import { renderApp } from '@/test/render-app';
import { demoId, mockState, type Schemas } from '@/mocks/data';

function failed(issues: Schemas['BuildError'][]) {
  mockState.current.builds.set('failed', {
    id: 'failed',
    project_id: demoId,
    engine: 'xelatex',
    status: 'error',
    has_pdf: false,
    pages: null,
    duration_ms: 1,
    warnings_count: 0,
    errors: issues,
    created_at: '2026-01-01T00:00:00Z',
  });
}
test('ошибка открывает исходник в указанной строке; журнал загружается по запросу', async () => {
  mockState.current.projects.get(demoId)!.files.get('main.tex')!.text = 'Первая\nВторая\nТретья';
  failed([
    {
      file: './main.tex',
      line: 2,
      message: 'Неизвестная команда',
      context: '1 Первая\n2 Вторая',
      severity: 'error',
    },
  ]);
  renderApp(`/projects/${demoId}`);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'main.tex:2' }));
  const element = await screen.findByRole('textbox', { name: 'Редактор main.tex' });
  await waitFor(() => expect(EditorView.findFromDOM(element)!.state.selection.main.head).toBe(7));
  await user.click(screen.getByRole('button', { name: 'Показать журнал сборки' }));
  expect(await screen.findByText(/Реальная компиляция не выполнялась/)).toBeInTheDocument();
});
test('ошибки без пути и с отсутствующим файлом остаются читаемыми без ложных переходов', async () => {
  failed([
    { file: null, line: null, message: 'Компилятор недоступен', context: '', severity: 'error' },
    {
      file: '../outside.tex',
      line: 1,
      message: 'Файл отсутствует',
      context: '<script>опасный текст</script>',
      severity: 'warning',
    },
  ]);
  renderApp(`/projects/${demoId}`);
  expect(await screen.findByText('Ошибка: Компилятор недоступен')).toBeInTheDocument();
  expect(screen.getByText(/файл недоступен в проекте/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '../outside.tex:1' })).not.toBeInTheDocument();
  expect(screen.getByText('<script>опасный текст</script>')).toBeInTheDocument();
});
