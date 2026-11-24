import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, expect, test, vi } from 'vitest';
import { demoId, mockState, type Schemas } from '@/mocks/data';
import { pdfFixture } from '@/mocks/pdf-fixture';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { buildKeys } from './pdf-queries';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test.each([
  [
    `inline; filename="report.pdf"; filename*=UTF-8''${encodeURIComponent('ЛР3_Фамилия.pdf')}`,
    'ЛР3_Фамилия.pdf',
  ],
  ['inline; filename="lab-3.pdf"', 'lab-3.pdf'],
  [null, 'document.pdf'],
])('обе кнопки скачивают PDF с именем из заголовка %s', async (disposition, filename) => {
  const build: Schemas['BuildOut'] = {
    id: 'download-build',
    project_id: demoId,
    status: 'ok',
    has_pdf: true,
    engine: 'xelatex',
    pages: 3,
    errors: [],
    warnings_count: 0,
    duration_ms: 10,
    created_at: '2026-01-01T00:00:00Z',
  };
  mockState.current.builds.set(build.id, build);
  const requestPdf = vi.fn(
    () =>
      new HttpResponse(pdfFixture, {
        headers: {
          'Content-Type': 'application/pdf',
          ...(disposition ? { 'Content-Disposition': disposition } : {}),
        },
      }),
  );
  server.use(http.get('/api/v1/builds/:bid/pdf', requestPdf));
  const createUrl = vi.fn(() => 'blob:download-test');
  vi.stubGlobal(
    'URL',
    class extends URL {
      static override createObjectURL = createUrl;
      static override revokeObjectURL = vi.fn();
    },
  );
  const download = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    download(this.download);
  });
  const { client } = renderApp(`/projects/${demoId}`);
  const user = userEvent.setup();
  const button = await screen.findByRole('button', { name: 'Скачать PDF' });
  await waitFor(() => expect(button).toBeEnabled());
  await screen.findByText('Обновления подключены');
  await waitFor(() => expect(client.isFetching({ queryKey: buildKeys.pdf(build.id) })).toBe(0));
  const loaded = requestPdf.mock.calls.length;
  await user.click(button);
  await user.click(screen.getByRole('button', { name: 'Экспорт PDF' }));
  expect(download.mock.calls).toEqual([[filename], [filename]]);
  expect(createUrl).toHaveBeenCalledWith(expect.objectContaining({ type: 'application/pdf' }));
  expect(requestPdf).toHaveBeenCalledTimes(loaded);
});
