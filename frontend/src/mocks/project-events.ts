import type { ProjectEvent } from '@/api/project-event';
import { mockState } from './data';

type Input = {
  [E in ProjectEvent['event']]: Omit<Extract<ProjectEvent, { event: E }>, 'id'>;
}[ProjectEvent['event']];
const streams = new WeakMap<
  typeof mockState.current,
  Map<
    string,
    {
      history: ProjectEvent[];
      sequence: number;
      listeners: Set<(event: ProjectEvent) => void>;
    }
  >
>();
export function mockProjectEvents(project: string) {
  let projects = streams.get(mockState.current);
  if (!projects) {
    projects = new Map();
    streams.set(mockState.current, projects);
  }
  let stream = projects.get(project);
  if (!stream) {
    stream = { history: [], sequence: 0, listeners: new Set() };
    projects.set(project, stream);
  }
  return stream;
}
export function emitMockEvent(project: string, input: Input) {
  const stream = mockProjectEvents(project);
  const event = { ...input, id: `${Date.now()}-${stream.sequence++}` };
  stream.history.push(event);
  if (stream.history.length > 1000) stream.history.shift();
  for (const listener of stream.listeners) listener(event);
}
