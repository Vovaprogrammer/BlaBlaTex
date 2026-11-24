import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { http, HttpResponse } from 'msw';
import { expect, test, vi } from 'vitest';
import type { components } from '@/api/schema';
import { demoId } from '@/mocks/data';
import { failure } from '@/mocks/responses';
import { emitMockEvent } from '@/mocks/project-events';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';

type Result = components['schemas']['CheckResult'];
const result: Result = {
  findings: [
    {
      check: 'title-empty',
      level: 'warning',
      message: 'Укажите группу',
      place: 'profile',
      field: 'group_name',
      file: null,
      line: null,
    },
    {
      check: 'title-empty',
      level: 'error',
      message: 'Заполните название работы',
      place: 'fields',
      field: 'report_title',
      file: null,
      line: null,
    },
    {
      check: 'ref-broken',
      level: 'error',
      message: 'Не найдена ссылка',
      place: 'file',
      field: null,
      file: 'main.tex',
      line: 3,
    },
    {
      check: 'build-failed',
      level: 'error',
      message: 'Проверьте сборку',
      place: 'build',
      field: null,
      file: null,
      line: null,
    },
  ],
  errors_count: 3,
  warnings_count: 1,
  build_id: null,
  pdf_checked: true,
};

async function openChecks() {
  const user = userEvent.setup();
  renderApp(`/projects/${demoId}`);
  await screen.findByText('Обновления подключены');
  await user.click(screen.getByRole('button', { name: 'Проверить отчёт' }));
  const dialog = await screen.findByRole('dialog', { name: 'Проверка отчёта' });
  return { user, dialog: within(dialog) };
}

test('проверка запускается по кнопке и открывает строку файла, ошибки идут первыми', async () => {
  const check = vi.fn(({ request }: { request: Request }) => {
    expect(new URL(request.url).searchParams.get('wait')).toBe('0');
    return HttpResponse.json(result);
  });
  server.use(http.post('/api/v1/projects/:pid/checks', check));
  renderApp(`/projects/${demoId}`);
  await screen.findByText('Обновления подключены');
  expect(check).not.toHaveBeenCalled();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Проверить отчёт' }));
  const dialog = within(await screen.findByRole('dialog', { name: 'Проверка отчёта' }));
  await dialog.findByRole('button', { name: 'Не найдена ссылка' });
  expect(dialog.getAllByRole('listitem')[0]).toHaveTextContent('Заполните название работы');
  expect(dialog.getAllByRole('listitem').at(-1)).toHaveTextContent('Укажите группу');
  await user.click(dialog.getByRole('button', { name: 'Не найдена ссылка' }));
  const editor = await screen.findByRole('textbox', { name: 'Редактор main.tex' });
  await waitFor(() => {
    const view = EditorView.findFromDOM(editor)!;
    expect(view.state.doc.lineAt(view.state.selection.main.head).number).toBe(3);
  });
});

test('находка открывает данные работы и выделяет нужное поле', async () => {
  server.use(http.post('/api/v1/projects/:pid/checks', () => HttpResponse.json(result)));
  const { user, dialog } = await openChecks();
  await user.click(await dialog.findByRole('button', { name: 'Заполните название работы' }));
  const form = within(await screen.findByRole('dialog', { name: 'Данные работы' }));
  await waitFor(() => expect(form.getByRole('textbox', { name: /Название работы/ })).toHaveFocus());
});

test.each(['profile', 'build'] as const)('находка ведёт к месту %s', async (place) => {
  server.use(http.post('/api/v1/projects/:pid/checks', () => HttpResponse.json(result)));
  const { user, dialog } = await openChecks();
  await user.click(
    await dialog.findByRole('button', {
      name: place === 'profile' ? 'Укажите группу' : 'Проверьте сборку',
    }),
  );
  if (place === 'profile')
    expect(await screen.findByRole('heading', { name: 'Профиль' })).toBeInTheDocument();
  else
    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Сборка отчёта' })).toHaveFocus(),
    );
});

test('после события сборки повторяет незавершённую проверку PDF', async () => {
  let complete = false;
  const check = vi.fn(() =>
    HttpResponse.json<Result>({
      findings: [],
      errors_count: 0,
      warnings_count: 0,
      build_id: 'checks-build',
      pdf_checked: complete,
    }),
  );
  server.use(http.post('/api/v1/projects/:pid/checks', check));
  const { dialog } = await openChecks();
  expect(
    await dialog.findByText('PDF ещё собирается, проверки по нему будут позже'),
  ).toBeInTheDocument();
  complete = true;
  await act(() =>
    emitMockEvent(demoId, {
      event: 'build.finished',
      data: { build_id: 'checks-build', status: 'ok', pages: 3, errors_count: 0 },
    }),
  );
  expect(await dialog.findByText('Замечаний не найдено.')).toBeInTheDocument();
  expect(check.mock.calls.length).toBeGreaterThanOrEqual(2);
});

test('ошибка проверки показывает сообщение сервера и повтор', async () => {
  let fail = true;
  server.use(
    http.post('/api/v1/projects/:pid/checks', () =>
      fail
        ? failure(500, 'internal', 'Проверка недоступна')
        : HttpResponse.json({ ...result, findings: [] }),
    ),
  );
  const { user, dialog } = await openChecks();
  expect(await dialog.findByRole('alert')).toHaveTextContent('Проверка недоступна');
  fail = false;
  await user.click(dialog.getByRole('button', { name: 'Повторить проверку' }));
  expect(await dialog.findByText('Замечаний не найдено.')).toBeInTheDocument();
});
