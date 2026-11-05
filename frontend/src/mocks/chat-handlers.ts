import { http, HttpResponse } from 'msw';
import { ownedProject, type Schemas } from './data';
import { failure, guard } from './responses';

export const chatHandlers = [
  http.get('/api/v1/projects/:pid/messages', ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    if (!ownedProject(String(params.pid))) return failure(404, 'not_found', 'Проект не найден');
    return HttpResponse.json<Schemas['MessageList']>({
      items: [],
      has_more: false,
      active_run: null,
    });
  }),
];
