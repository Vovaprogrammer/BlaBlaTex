import { http } from 'msw/http';
import { authHandlers } from './auth-handlers';
import { projectHandlers } from './project-handlers';
import { fileHandlers } from './file-handlers';
import { buildHandlers } from './build-handlers';
import { eventHandlers } from './event-handlers';
import { materialHandlers } from './material-handlers';
import { failure } from './responses';

export const handlers = [
  ...authHandlers,
  ...projectHandlers,
  ...fileHandlers,
  ...buildHandlers,
  ...eventHandlers,
  ...materialHandlers,
  http.all('/api/v1/*', () => failure(404, 'not_found', 'Адрес API не найден')),
];
