import { http, HttpResponse } from 'msw/http';
import { mockState, ownedProject } from './data';
import type { Schemas } from './data';
import { failure, guard } from './responses';
import { pdfFixture } from './pdf-fixture';

function ownedBuild(id: string) {
  const build = mockState.current.builds.get(id);
  return build && ownedProject(build.project_id) ? build : undefined;
}
export const buildHandlers = [
  http.post('/api/v1/projects/:pid/builds', ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const value = ownedProject(String(params.pid));
    if (!value) return failure(404, 'not_found', 'Проект не найден');
    const build: Schemas['BuildOut'] = {
      id: crypto.randomUUID(),
      project_id: value.project.id,
      status: 'queued',
      engine: value.project.engine,
      pages: null,
      duration_ms: 0,
      warnings_count: 0,
      errors: [],
      has_pdf: false,
      created_at: new Date().toISOString(),
    };
    mockState.current.builds.set(build.id, build);
    return HttpResponse.json<Schemas['BuildOut']>(build, { status: 202 });
  }),
  http.get('/api/v1/projects/:pid/builds/latest', ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const value = ownedProject(String(params.pid));
    if (!value) return failure(404, 'not_found', 'Проект не найден');
    const latest = [...mockState.current.builds.values()]
      .filter((build) => build.project_id === value.project.id)
      .filter(
        (build) =>
          new URL(request.url).searchParams.get('status') !== 'ok' || build.status === 'ok',
      )
      .at(-1);
    return latest
      ? HttpResponse.json<Schemas['BuildOut']>(latest)
      : failure(404, 'not_found', 'Сборок пока нет');
  }),
  http.get('/api/v1/builds/:bid', ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const build = ownedBuild(String(params.bid));
    if (!build) return failure(404, 'not_found', 'Сборка не найдена');
    // Детерминированная модель очереди для проверок, не настоящая компиляция.
    if (build.status === 'queued') build.status = 'running';
    else if (build.status === 'running') {
      build.status = 'ok';
      build.has_pdf = true;
      build.pages = 3;
    }
    return HttpResponse.json<Schemas['BuildOut']>(build);
  }),
  http.get(
    '/api/v1/builds/:bid/pdf',
    ({ request, params }) =>
      guard(request) ??
      (ownedBuild(String(params.bid))?.has_pdf
        ? new HttpResponse(pdfFixture, { headers: { 'Content-Type': 'application/pdf' } })
        : failure(404, 'not_found', 'Сборка не найдена')),
  ),
  http.get(
    '/api/v1/builds/:bid/log',
    ({ request, params }) =>
      guard(request) ??
      (ownedBuild(String(params.bid))
        ? HttpResponse.text(
            'Демонстрационный режим: выданы три заранее заданные PDF-страницы. Реальная компиляция не выполнялась.',
          )
        : failure(404, 'not_found', 'Сборка не найдена')),
  ),
];
