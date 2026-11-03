import { http, HttpResponse } from 'msw/http';
import {
  mockState,
  newFile,
  newProject,
  ownedProject,
  refreshGeneratedFiles,
  template,
} from './data';
import type { Schemas } from './data';
import { checkFields, failure, guard, invalid, readBody, validText } from './responses';

export const projectHandlers = [
  http.get('/api/v1/templates', () =>
    HttpResponse.json<Schemas['TemplateList']>({
      items: [
        {
          slug: template.slug,
          version: template.version,
          kind: template.kind,
          title: template.title,
          discipline: template.discipline,
        },
      ],
    }),
  ),
  http.get('/api/v1/templates/:slug', ({ params }) =>
    params.slug === template.slug
      ? HttpResponse.json<Schemas['TemplateDetail']>(template)
      : failure(404, 'not_found', 'Шаблон не найден'),
  ),
  http.get(
    '/api/v1/projects',
    ({ request }) =>
      guard(request) ??
      HttpResponse.json<Schemas['ProjectList']>({
        items: [...mockState.current.projects.values()]
          .filter((item) => item.owner === mockState.current.currentUserId)
          .map((item) => item.project),
      }),
  ),
  http.post('/api/v1/projects', async ({ request }) => {
    const denied = guard(request);
    if (denied) return denied;
    const body = await readBody(request);
    if (!validText(body.title) || !body.title.length) return invalid('title');
    if (body.template_slug !== template.slug) return failure(404, 'not_found', 'Шаблон не найден');
    const fields = checkFields(body.fields);
    if (fields instanceof Response) return fields;
    const project = { ...newProject(crypto.randomUUID()), title: body.title, fields };
    mockState.current.projects.set(project.id, {
      project,
      owner: mockState.current.currentUserId!,
      files: new Map([
        ['main.tex', newFile('main.tex', '\\section{Цель работы}\n')],
        ['meta.tex', newFile('meta.tex', '% Создаётся автоматически.\n', 'generated')],
      ]),
    });
    return HttpResponse.json<Schemas['ProjectOut']>(project, { status: 201 });
  }),
  http.get(
    '/api/v1/projects/:pid',
    ({ request, params }) =>
      guard(request) ??
      (ownedProject(String(params.pid))
        ? HttpResponse.json<Schemas['ProjectOut']>(ownedProject(String(params.pid))!.project)
        : failure(404, 'not_found', 'Проект не найден')),
  ),
  http.patch('/api/v1/projects/:pid', async ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const value = ownedProject(String(params.pid));
    if (!value) return failure(404, 'not_found', 'Проект не найден');
    const body = await readBody(request);
    let title = value.project.title;
    let fields = value.project.fields;
    if (body.title != null) {
      if (!validText(body.title) || !body.title.length) return invalid('title');
      title = body.title;
    }
    if (body.fields != null) {
      const checked = checkFields(body.fields);
      if (checked instanceof Response) return checked;
      fields = checked;
      refreshGeneratedFiles(value.owner, value.project.id);
    }
    value.project.title = title;
    value.project.fields = fields;
    value.project.updated_at = new Date().toISOString();
    return HttpResponse.json<Schemas['ProjectOut']>(value.project);
  }),
  http.delete('/api/v1/projects/:pid', ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const id = String(params.pid);
    if (!ownedProject(id)) return failure(404, 'not_found', 'Проект не найден');
    mockState.current.projects.delete(id);
    return new HttpResponse(null, { status: 204 });
  }),
];
