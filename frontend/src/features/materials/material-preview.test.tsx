import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterAll, beforeAll, expect, test, vi } from 'vitest';
import { Blob as NodeBlob } from 'node:buffer';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { demoId, mockState, newFile, type Schemas } from '@/mocks/data';
import { emitMockEvent } from '@/mocks/project-events';
import { pdfFixture } from '@/mocks/pdf-fixture';

beforeAll(() => {
  vi.stubGlobal('Blob', NodeBlob);
  vi.stubGlobal(
    'URL',
    class extends URL {
      static override createObjectURL = vi.fn(() => 'blob:test-image');
      static override revokeObjectURL = vi.fn();
    },
  );
});
afterAll(() => vi.unstubAllGlobals());
function add(path: string, mime = 'text/plain', body = 'Текст материала') {
  const file = newFile(`materials/${path}`, body, 'material');
  file.info.mime = mime;
  if (mime !== 'text/plain') {
    file.info.kind = 'binary';
    file.blob = new Blob([mime === 'application/pdf' ? pdfFixture : body], { type: mime });
  }
  mockState.current.projects.get(demoId)!.files.set(file.info.path, file);
  return file;
}
async function open(name: string) {
  renderApp(`/projects/${demoId}`);
  await userEvent.setup().click(await screen.findByRole('button', { name: `Открыть ${name}` }));
}

test('PDF материала открывается в просмотрщике с отдельной постоянной вкладкой результата', async () => {
  add('методичка.pdf', 'application/pdf');
  await open('методичка.pdf');
  await waitFor(() =>
    expect(screen.getByRole('spinbutton', { name: 'Номер страницы PDF' })).toHaveAttribute(
      'max',
      '3',
    ),
  );
  expect(screen.getByRole('tab', { name: 'PDF' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Скачать файл' })).toBeInTheDocument();
});

test('изображение открывается через Blob URL и освобождает URL при закрытии', async () => {
  add('схема.svg', 'image/svg+xml', '<svg xmlns="http://www.w3.org/2000/svg" />');
  await open('схема.svg');
  expect(await screen.findByRole('img', { name: 'materials/схема.svg' })).toHaveAttribute(
    'src',
    'blob:test-image',
  );
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: 'Закрыть materials/схема.svg' }));
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test-image');
});

test('код остаётся редактируемым, а извлечённый текст читается отдельно и постранично', async () => {
  add('example.py', 'text/plain', 'print(1)');
  const text = 'x'.repeat(20_000) + 'Последняя часть';
  server.use(
    http.get('/api/v1/projects/:pid/material-text', ({ request }) => {
      const url = new URL(request.url);
      const offset = Number(url.searchParams.get('offset') ?? 0);
      const limit = Number(url.searchParams.get('limit') ?? 20_000);
      return HttpResponse.json<Schemas['MaterialTextOut']>({
        path: 'materials/example.py',
        status: 'ready',
        method: 'text',
        pages: null,
        description: null,
        error: null,
        text: text.slice(offset, offset + limit),
        total: text.length,
        offset,
      });
    }),
  );
  await open('example.py');
  expect(
    await screen.findByRole('textbox', { name: 'Редактор materials/example.py' }),
  ).toHaveAttribute('aria-readonly', 'false');
  await userEvent.setup().click(screen.getByRole('button', { name: 'Текст для помощника' }));
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Далее' }));
  expect(await screen.findByText('Последняя часть')).toBeInTheDocument();
});

test('событие material.ready обновляет значок и ошибку без потери исходного файла', async () => {
  add('данные.txt');
  let status: Schemas['MaterialTextOut']['status'] = 'pending';
  server.use(
    http.get('/api/v1/projects/:pid/material-text', () =>
      HttpResponse.json<Schemas['MaterialTextOut']>({
        path: 'materials/данные.txt',
        status,
        text: null,
        total: 0,
        offset: 0,
        method: null,
        description: null,
        pages: null,
        error: status === 'failed' ? 'Не получилось прочитать текст файла' : null,
      }),
    ),
  );
  await open('данные.txt');
  await screen.findByText('Обрабатывается');
  status = 'failed';
  await act(() =>
    emitMockEvent(demoId, {
      event: 'material.ready',
      data: { path: 'materials/данные.txt', status: 'failed' },
    }),
  );
  await screen.findByText('Ошибка обработки');
  const row = screen.getByRole('button', { name: 'Открыть данные.txt' });
  expect(within(row).getByRole('img', { name: 'Ошибка обработки' })).toBeInTheDocument();
  expect(
    screen.getByRole('textbox', { name: 'Редактор materials/данные.txt' }),
  ).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Текст для помощника' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не получилось прочитать текст файла');
});

test('статус после открытия читается запросом, готовность не выводится из факта загрузки', async () => {
  add('готово.txt');
  await open('готово.txt');
  await waitFor(() => expect(screen.getByText('Готово для помощника')).toBeInTheDocument());
});
