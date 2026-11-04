import { afterEach, expect, test, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { failure } from '@/mocks/responses';
import { demoId } from '@/mocks/data';
import { listenProjectEvents } from './project-events';
import { api } from './client';
import { parseProjectEvent } from './project-event';

const controllers: AbortController[] = [];
afterEach(() => {
  controllers.splice(0).forEach((controller) => controller.abort());
  vi.restoreAllMocks();
  vi.useRealTimers();
});
const wire = (id: string) =>
  `id: ${id}\nevent: file.changed\ndata: {"path":"main.tex","version":2,"changeset_id":null,"author":"ai"}\n\n`;
const stream = (text: string) =>
  new HttpResponse(text, {
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
  });
function start() {
  const controller = new AbortController();
  controllers.push(controller);
  const event = vi.fn();
  const status = vi.fn();
  const result = listenProjectEvents(demoId, controller.signal, { event, status });
  return { controller, event, status, result };
}

test('обрыв повторяет запрос с Last-Event-ID, комментарии и дубликаты пропускаются', async () => {
  const credentialCheck = {
    onRequest({ request }: { request: Request }) {
      expect(request.credentials).toBe('include');
    },
  };
  api.use(credentialCheck);
  const headers: (string | null)[] = [];
  server.use(
    http.get('/api/v1/projects/:pid/events', ({ request }) => {
      headers.push(request.headers.get('last-event-id'));
      return stream(': keep-alive\n\n' + wire('100-0') + (headers.length > 1 ? wire('100-1') : ''));
    }),
  );
  const { event, controller, result } = start();
  await waitFor(() => expect(event).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(event).toHaveBeenCalledTimes(2), { timeout: 3000 });
  expect(headers.slice(0, 2)).toEqual([null, '100-0']);
  expect(event.mock.calls.map(([value]) => value.id)).toEqual(['100-0', '100-1']);
  controller.abort();
  await result;
  api.eject(credentialCheck);
});

test('серия ошибок увеличивает паузу 1, 2, 4 секунды; отмена прекращает повторы', async () => {
  const times: number[] = [];
  const requests = vi.fn(() => {
    times.push(Date.now());
    return failure(500, 'internal', 'Поток недоступен');
  });
  server.use(http.get('/api/v1/projects/:pid/events', requests));
  const { status, controller, result } = start();
  await waitFor(() => expect(status).toHaveBeenLastCalledWith('retrying'));
  await waitFor(() => expect(requests).toHaveBeenCalledTimes(4), { timeout: 9000 });
  expect(times[1]! - times[0]!).toBeGreaterThanOrEqual(950);
  expect(times[2]! - times[1]!).toBeGreaterThanOrEqual(1950);
  expect(times[3]! - times[2]!).toBeGreaterThanOrEqual(3950);
  controller.abort();
  await result;
  const count = requests.mock.calls.length;
  await new Promise((resolve) => setTimeout(resolve, 150));
  expect(requests).toHaveBeenCalledTimes(count);
});

test.each([401, 403, 404])('ошибка %s завершает поток с сообщением API', async (status) => {
  const requests = vi.fn(() => failure(status, 'not_found', 'Нет доступа к проекту'));
  server.use(http.get('/api/v1/projects/:pid/events', requests));
  const { result } = start();
  await expect(result).rejects.toMatchObject({ status, message: 'Нет доступа к проекту' });
  expect(requests).toHaveBeenCalledTimes(1);
});

test('повреждённый ответ завершается понятной ошибкой', async () => {
  server.use(
    http.get('/api/v1/projects/:pid/events', () =>
      stream(wire('100-0').replace('"version":2', '"version":"wrong"')),
    ),
  );
  await expect(start().result).rejects.toMatchObject({ code: 'invalid_event_stream' });
});

test('контракт проверяет seq и все данные события, включая старый null changeset', () => {
  expect(
    parseProjectEvent('file.deleted', '1-0', '{"path":"a.tex","changeset_id":null}').event,
  ).toBe('file.deleted');
  expect(() =>
    parseProjectEvent('run.delta', '2-0', '{"run_id":"r","message_id":"m","text":"x"}'),
  ).toThrow();
  expect(
    parseProjectEvent('run.delta', '2-0', '{"run_id":"r","message_id":"m","seq":1,"text":"x"}')
      .event,
  ).toBe('run.delta');
});
