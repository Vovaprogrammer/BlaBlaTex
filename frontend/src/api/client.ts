import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './schema';
import { ApiError } from './api-error';

const middleware: Middleware = {
  onRequest({ request }) {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
      request.headers.set('X-CSRF-Protection', '1');
    }
  },
  async onResponse({ response }) {
    if (!response.ok) throw await ApiError.fromResponse(response);
  },
  onError({ error, request }) {
    if (request.signal.aborted) throw error;
    return new ApiError(
      0,
      'network_error',
      'Не удалось связаться с сервером. Проверьте соединение.',
    );
  },
};

export function createApiClient(baseUrl = window.location.origin) {
  const client = createClient<paths>({
    baseUrl,
    credentials: 'include',
    fetch: (request) => globalThis.fetch(request),
    bodySerializer: (body: unknown) =>
      body instanceof FormData || typeof body === 'string' ? body : JSON.stringify(body),
  });
  client.use(middleware);
  return client;
}

export const api = createApiClient();
