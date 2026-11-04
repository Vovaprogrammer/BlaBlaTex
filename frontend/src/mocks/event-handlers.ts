import { http, HttpResponse } from 'msw';
import { guard, failure } from './responses';
import { ownedProject } from './data';
import { mockProjectEvents } from './project-events';
import type { ProjectEvent } from '@/api/project-event';

export const eventHandlers = [
  http.get('/api/v1/projects/:pid/events', ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    if (!ownedProject(String(params.pid))) return failure(404, 'not_found', 'Проект не найден');
    const events = mockProjectEvents(String(params.pid));
    let dispose = () => {};
    return new HttpResponse(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(': keep-alive\n\n'));
          const send = (event: ProjectEvent) =>
            controller.enqueue(
              new TextEncoder().encode(
                `id: ${event.id}\nevent: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`,
              ),
            );
          const last = request.headers.get('Last-Event-ID');
          if (last) {
            const index = events.history.findIndex((event) => event.id === last);
            for (const event of events.history.slice(index + 1)) send(event);
          }
          events.listeners.add(send);
          dispose = () => events.listeners.delete(send);
          request.signal.addEventListener(
            'abort',
            () => {
              dispose();
              controller.close();
            },
            { once: true },
          );
        },
        cancel() {
          dispose();
        },
      }),
      { headers: { 'Content-Type': 'text/event-stream' } },
    );
  }),
];
