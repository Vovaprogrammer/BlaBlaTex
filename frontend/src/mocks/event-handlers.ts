import { http, HttpResponse } from 'msw';
import { guard, failure } from './responses';
import { ownedProject } from './data';

export const eventHandlers = [
  http.get('/api/v1/projects/:pid/events', ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    if (!ownedProject(String(params.pid))) return failure(404, 'not_found', 'Проект не найден');
    return new HttpResponse(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(': keep-alive\n\n'));
          request.signal.addEventListener('abort', () => controller.close(), { once: true });
        },
      }),
      { headers: { 'Content-Type': 'text/event-stream' } },
    );
  }),
];
