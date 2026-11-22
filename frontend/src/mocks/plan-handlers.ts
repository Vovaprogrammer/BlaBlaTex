import { http, HttpResponse } from 'msw';
import { queueReply } from './chat-handlers';
import { mockState, ownedProject, template, type Schemas } from './data';
import { emitMockEvent } from './project-events';
import { failure, guard } from './responses';

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
