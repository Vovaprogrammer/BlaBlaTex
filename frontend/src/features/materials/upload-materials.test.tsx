import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { http } from 'msw';
import { afterAll, beforeAll, expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { demoId, mockState, newFile } from '@/mocks/data';
import { failure } from '@/mocks/responses';

// Прогресс XHR проверяется отдельно и в Chrome; здесь MSW разбирает настоящий multipart.
vi.mock('@/api/upload-fetch', async () => {
  const { Request: EncoderRequest } = await import('undici');
  return {
    uploadFetch: (form: FormData) => async (request: Request) => {
      const headers = new Headers(request.headers);
      headers.delete('Content-Type');
      const encoded = new EncoderRequest(request.url, {
        method: request.method,
        headers: Object.fromEntries(headers),
        // Глобальный FormData в этом файле заменён на класс Undici ниже.
        body: form as unknown as import('undici').FormData,
      });
      const encodedHeaders: Record<string, string> = {};
      encoded.headers.forEach((value, key) => {
        encodedHeaders[key] = value;
      });
      return fetch(
        new Request(request, { headers: encodedHeaders, body: await encoded.arrayBuffer() }),
      );
    },
  };
});

// Multipart и MSW используют один набор Web API Node, без смешивания с Blob jsdom.
beforeAll(async () => {
  const { Blob, File } = await import('node:buffer');
  const { FormData } = await import('undici');
  vi.stubGlobal('File', File);
  vi.stubGlobal('Blob', Blob);
  vi.stubGlobal('FormData', FormData);
});
afterAll(() => vi.unstubAllGlobals());

async function open() {
  const app = renderApp(`/projects/${demoId}`);
  const input = await screen.findByLabelText('Выбрать материалы');
  return { ...app, input };
}
const text = (name: string, body = 'Материал для отчёта') =>
  new File([body], name, { type: 'text/plain' });
const uploadRegion = () => within(screen.getByRole('region', { name: 'Загрузка материалов' }));

test('вставка и перетаскивание в чат загружают файлы в материалы и добавляют ссылки в сообщение', async () => {
  await open();
  const composer = within(await screen.findByRole('form', { name: 'Написать сообщение' }));
  const input = composer.getByRole('textbox');
  await screen.findByText('Опишите, что нужно сделать с документом.');
  fireEvent.paste(input, { clipboardData: { files: [text('описание.txt')] } });
  expect(await composer.findByText('описание.txt')).toBeInTheDocument();
  fireEvent.drop(input, { dataTransfer: { types: ['Files'], files: [text('данные.csv')] } });
  expect(await composer.findByText('данные.csv')).toBeInTheDocument();
  expect(mockState.current.projects.get(demoId)?.files.has('materials/данные.csv')).toBe(true);
  await userEvent.setup().click(composer.getByRole('button', { name: 'Отправить' }));
  const list = within(screen.getByRole('region', { name: 'Сообщения' }));
  expect(
    await list.findByText(/materials\/описание\.txt.*materials\/данные\.csv/),
  ).toBeInTheDocument();
});

test('выбор нескольких файлов отправляет multipart через API и обновляет дерево', async () => {
  const { input, client } = await open();
  await userEvent.setup().upload(input, [text('описание.txt'), text('script.py', 'print(1)')]);
  await waitFor(() => {
    const mutation = client
      .getMutationCache()
      .getAll()
      .find((entry) => entry.options.mutationKey?.at(-1) === 'upload');
    if (mutation?.state.error) throw mutation.state.error;
    expect(mutation?.state.status).toBe('success');
  });
  await screen.findByText('Загружено файлов: 2');
  expect(await screen.findByRole('button', { name: 'Открыть описание.txt' })).toBeInTheDocument();
  expect(mockState.current.projects.get(demoId)!.files.get('materials/script.py')?.text).toBe(
    'print(1)',
  );
});

test('выбранная подпапка материалов становится местом загрузки', async () => {
  const folder = newFile('materials/скриншоты');
  folder.info.kind = 'folder';
  mockState.current.projects.get(demoId)!.files.set(folder.info.path, folder);
  const { input } = await open();
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Папка скриншоты' }));
  await userEvent.setup().upload(input, text('данные.txt'));
  await screen.findByText('Загружено файлов: 1');
  expect(mockState.current.projects.get(demoId)!.files.has('materials/скриншоты/данные.txt')).toBe(
    true,
  );
});

test('внешние файлы можно бросить прямо на папку Материалы', async () => {
  await open();
  const folder = await screen.findByRole('button', { name: 'Папка Материалы' });
  fireEvent.drop(folder, { dataTransfer: { types: ['Files'], files: [text('из-drop.txt')] } });
  await screen.findByText('Загружено файлов: 1');
  expect(await screen.findByRole('button', { name: 'Открыть из-drop.txt' })).toBeInTheDocument();
});

test('удалённая выбранная папка не создаётся заново следующей загрузкой', async () => {
  const folder = newFile('materials/old');
  folder.info.kind = 'folder';
  const files = mockState.current.projects.get(demoId)!.files;
  files.set(folder.info.path, folder);
  const { input, client } = await open();
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Папка old' }));
  files.delete(folder.info.path);
  await act(() => client.invalidateQueries({ queryKey: ['projects', demoId, 'tree'] }));
  await userEvent.setup().upload(input, text('new.txt'));
  await screen.findByText('Загружено файлов: 1');
  expect(files.has('materials/new.txt')).toBe(true);
  expect(files.has('materials/old')).toBe(false);
});

test.each([413, 415])('ошибка %s показывает сообщение сервера, повтор доступен', async (status) => {
  server.use(
    http.post('/api/v1/projects/:pid/upload', () =>
      failure(
        status,
        status === 413 ? 'payload_too_large' : 'unsupported_file_type',
        'Не подошёл файл: проверьте формат и лимит 20 МБ',
      ),
    ),
  );
  const { input } = await open();
  await userEvent.setup().upload(input, text('данные.txt'));
  expect(await uploadRegion().findByRole('alert')).toHaveTextContent(
    'Не подошёл файл: проверьте формат и лимит 20 МБ',
  );
  expect(screen.getByRole('button', { name: 'Загрузить материалы' })).toBeEnabled();
});

test('файл больше лимита не отправляется', async () => {
  const { input } = await open();
  await userEvent
    .setup()
    .upload(
      input,
      new File([new Uint8Array(20 * 1024 ** 2 + 1)], 'large.pdf', { type: 'application/pdf' }),
    );
  expect(await uploadRegion().findByRole('alert')).toHaveTextContent('больше 20 МБ');
});

test('загрузка не заменяет файл с несохранённым текстом', async () => {
  const material = newFile('materials/данные.txt', 'Исходник', 'material');
  mockState.current.projects.get(demoId)!.files.set(material.info.path, material);
  const { input } = await open();
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Открыть данные.txt' }));
  const editor = EditorView.findFromDOM(
    await screen.findByRole('textbox', { name: 'Редактор materials/данные.txt' }),
  )!;
  await act(() =>
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: 'Черновик' } }),
  );
  await userEvent.setup().upload(input, text('данные.txt', 'Подмена'));
  await waitFor(() =>
    expect(uploadRegion().getByRole('alert')).toHaveTextContent('Сначала сохраните изменения'),
  );
  expect(material.text).toBe('Исходник');
});
