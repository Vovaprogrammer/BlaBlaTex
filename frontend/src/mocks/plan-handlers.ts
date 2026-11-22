import { http, HttpResponse } from 'msw';
import { activeRun, queueReply } from './chat-handlers';
import { isRecord } from '@/api/api-error';
import { mockState, ownedProject, template, type Schemas } from './data';
import { emitMockEvent } from './project-events';
import { failure, guard, invalid, readBody } from './responses';

type Plan = Schemas['PlanOut'];
type Project = NonNullable<ReturnType<typeof ownedProject>>;
const plans = new WeakMap<Project, Plan>();
const route = '/api/v1/projects/:pid/plan';

function materialPaths(project: Project) {
  return [...project.files.values()]
    .filter(({ info }) => info.kind !== 'folder' && info.role === 'material')
    .map(({ info }) => info.path)
    .sort();
}

function storePlan(project: Project, plan: Plan) {
  plans.set(project, plan);
  const { status, updated_at } = plan;
  emitMockEvent(project.project.id, { event: 'plan.updated', data: { status, updated_at } });
  return plan;
}

function currentPlan(project: Project, plan: Plan): Plan {
  const paths = materialPaths(project);
  const sections = plan.plan.sections.map((section) => ({
    ...section,
    materials: section.materials.filter((path) => paths.includes(path)),
  }));
  const used = new Set(sections.flatMap((section) => section.materials));
  return { ...plan, plan: { sections, unassigned: paths.filter((path) => !used.has(path)) } };
}

export const planHandlers = [
  http.get(route, ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    const project = ownedProject(String(params.pid));
    if (!project) return failure(404, 'not_found', 'Проект не найден');
    const plan = plans.get(project);
    return plan
      ? HttpResponse.json(currentPlan(project, plan))
      : failure(404, 'not_found', 'План ещё не составлен');
  }),
  http.put(route, async ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    const id = String(params.pid);
    const project = ownedProject(id);
    if (!project) return failure(404, 'not_found', 'Проект не найден');
    const body = await readBody(request);
    const active = activeRun(id);
    if (active)
      return failure(423, 'project_locked', 'Помощник уже работает.', { run_id: active.id });
    if (!Array.isArray(body.sections) || body.sections.length > 100) return invalid('sections');

    const paths = new Set(materialPaths(project));
    const sections = new Map(
      template.sections.map(({ id, title }) => [
        id,
        {
          section_id: id,
          title,
          note: '',
          materials: [] as string[],
        },
      ]),
    );
    const seen = new Set<string>();
    for (const [index, item] of body.sections.entries()) {
      const field = `sections.${index}`;
      if (!isRecord(item) || typeof item.section_id !== 'string') return invalid(field);
      const section = sections.get(item.section_id);
      if (!section || seen.has(item.section_id)) return invalid(`${field}.section_id`);
      seen.add(item.section_id);
      const materials = item.materials ?? [];
      if (!Array.isArray(materials) || materials.length > 500) return invalid(`${field}.materials`);
      for (const [index, path] of materials.entries()) {
        if (typeof path !== 'string' || !paths.has(path) || section.materials.includes(path))
          return invalid(`${field}.materials.${index}`);
        section.materials.push(path);
      }
      if (typeof item.note !== 'string' || Array.from(item.note).length > 2000)
        return invalid(`${field}.note`);
      section.note = item.note;
    }
    const saved = storePlan(project, {
      plan: { sections: [...sections.values()], unassigned: [] },
      status: 'draft',
      updated_at: new Date().toISOString(),
    });
    return HttpResponse.json(currentPlan(project, saved));
  }),
  http.post(route + '/confirm', ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    const id = String(params.pid);
    const project = ownedProject(id);
    if (!project) return failure(404, 'not_found', 'Проект не найден');
    const plan = plans.get(project);
    if (!plan) return failure(404, 'not_found', 'План ещё не составлен');
    const response = queueReply(id, 'Напиши отчёт по плану', 'report');
    if (response.ok)
      storePlan(project, { ...plan, status: 'confirmed', updated_at: new Date().toISOString() });
    return response;
  }),
  http.post(route, ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    const id = String(params.pid);
    const project = ownedProject(id);
    if (!project) return failure(404, 'not_found', 'Проект не найден');
    const session = mockState.current;
    return queueReply(id, 'Составь план отчёта', 'plan', () => {
      const [first] = materialPaths(project);
      if (mockState.current === session) {
        storePlan(project, {
          plan: {
            sections: template.sections.map((section, index) => ({
              section_id: section.id,
              title: section.title,
              materials: index === 0 && first ? [first] : [],
              note: section.guide,
            })),
            unassigned: [],
          },
          status: 'draft',
          updated_at: new Date().toISOString(),
        });
      }
      return { type: 'plan' };
    });
  }),
];
