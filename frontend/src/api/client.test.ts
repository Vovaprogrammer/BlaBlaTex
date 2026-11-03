import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import { server } from '@/test/server';
import { createApiClient } from './client';
import { ApiError } from './api-error';
import type { components } from './schema';

const baseUrl = 'http://localhost:5173';
const client = createApiClient(baseUrl);
const pid = '00000000-0000-4000-8000-000000000001';

test('чтение передаёт cookie без ненужного CSRF-заголовка', async () => {
  const checkingClient = createApiClient(baseUrl);
  checkingClient.use({
    onRequest({ request }) {
      expect(request.credentials).toBe('include');
    },
  });
  server.use(
    http.get(`${baseUrl}/api/v1/health`, ({ request }) => {
      expect(request.headers.has('X-CSRF-Protection')).toBe(false);
      return HttpResponse.json({ status: 'ok' });
    }),
  );
  expect((await checkingClient.GET('/api/v1/health')).data).toEqual({ status: 'ok' });
});

test('изменяющий запрос передаёт защитный заголовок и понимает ответ 204', async () => {
  server.use(
    http.post(`${baseUrl}/api/v1/auth/logout`, async ({ request }) => {
      expect(request.headers.get('X-CSRF-Protection')).toBe('1');
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const result = await client.POST('/api/v1/auth/logout');
  expect(result.response.status).toBe(204);
  expect(result.data).toBeUndefined();
});

test('JSON тела не превращается в текстовый формат', async () => {
  server.use(
    http.post(`${baseUrl}/api/v1/auth/login`, async ({ request }) => {
      expect(request.headers.get('Content-Type')).toContain('application/json');
      expect(await request.json()).toEqual({
        email: 'student@example.com',
        password: 'test-password',
      });
      return HttpResponse.json(
        { error: { code: 'unauthorized', message: 'Неверный email или пароль', details: {} } },
        { status: 401 },
      );
    }),
  );
  await expect(
    client.POST('/api/v1/auth/login', {
      body: { email: 'student@example.com', password: 'test-password' },
    }),
  ).rejects.toMatchObject({ status: 401, code: 'unauthorized' });
});

test('файлы передаются текстом, сохраняются заголовки версий', async () => {
  const url = `${baseUrl}/api/v1/projects/${pid}/files/main.tex`;
  const source = '\\section{Цель работы}';
  server.use(
    http.get(url, () => HttpResponse.text(source, { headers: { ETag: '"7"' } })),
    http.put(url, async ({ request }) => {
      expect(await request.text()).toBe(source);
      expect(request.headers.get('Content-Type')).toContain('text/plain');
      expect(request.headers.get('If-Match')).toBe('"7"');
      expect(request.headers.get('X-CSRF-Protection')).toBe('1');
      return HttpResponse.json<components['schemas']['FileInfo']>({
        path: 'main.tex',
        kind: 'text',
        role: 'source',
        mime: 'text/plain',
        size: new TextEncoder().encode(source).length,
        version: 8,
        updated_at: '2026-01-01T00:00:00Z',
      });
    }),
  );
  const params = { path: { pid, path: 'main.tex' } };
  const result = await client.GET('/api/v1/projects/{pid}/files/{path}', {
    params,
    parseAs: 'text',
  });
  expect(result.data).toBe(source);
  await client.PUT('/api/v1/projects/{pid}/files/{path}', {
    params,
    body: source,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'If-Match': result.response.headers.get('ETag'),
    },
  });
});

test('конфликт файла сохраняет статус, сообщение и текущую версию', async () => {
  const error: components['schemas']['ErrorResponse'] = {
    error: {
      code: 'file_conflict',
      message: 'Файл изменён в другом месте',
      details: { current_version: 7 },
    },
  };
  server.use(http.get(`${baseUrl}/api/v1/health`, () => HttpResponse.json(error, { status: 412 })));
  await expect(client.GET('/api/v1/health')).rejects.toMatchObject({
    name: 'ApiError',
    status: 412,
    code: 'file_conflict',
    message: error.error.message,
    details: { current_version: 7 },
  });
});

test('PDF не разбирается как JSON', async () => {
  const fixture = new TextEncoder().encode('%PDF-test-fixture');
  server.use(
    http.get(
      `${baseUrl}/api/v1/builds/${pid}/pdf`,
      () => new HttpResponse(fixture, { headers: { 'Content-Type': 'application/pdf' } }),
    ),
  );
  const result = await client.GET('/api/v1/builds/{bid}/pdf', {
    params: { path: { bid: pid } },
    parseAs: 'arrayBuffer',
  });
  expect(Array.from(new Uint8Array(result.data!))).toEqual(Array.from(fixture));
});

test('HTML ошибки прокси не попадает в интерфейс', async () => {
  server.use(
    http.get(`${baseUrl}/api/v1/health`, () =>
      HttpResponse.html('<h1>upstream unavailable</h1>', { status: 502 }),
    ),
  );
  await expect(client.GET('/api/v1/health')).rejects.toMatchObject({
    status: 502,
    code: 'http_error',
    message: 'Не удалось выполнить запрос. Попробуйте ещё раз.',
  });
});

test('сбой сети превращается в понятную ошибку', async () => {
  server.use(http.get(`${baseUrl}/api/v1/health`, () => HttpResponse.error()));
  await expect(client.GET('/api/v1/health')).rejects.toBeInstanceOf(ApiError);
});

test('отмена запроса не выдаётся за сбой сети', async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(client.GET('/api/v1/health', { signal: controller.signal })).rejects.toMatchObject({
    name: 'AbortError',
  });
});
