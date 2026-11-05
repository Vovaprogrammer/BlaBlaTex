import { z } from 'zod';
import type { components } from './schema';

export type ProjectEvent = components['schemas']['ProjectEvent'];
const id = z.string();
const count = z.number().int().nonnegative();
const changeset = { changeset_id: id.nullable() };
const run = { run_id: id };
const message = { ...run, message_id: id };
const tool = { ...run, call_id: id, seq: count, summary: z.string() };
const envelope = <T extends ProjectEvent['event'], D extends z.ZodRawShape>(event: T, data: D) =>
  z.object({ id: z.string().regex(/^\d+-\d+$/), event: z.literal(event), data: z.object(data) });

const events = [
  envelope('file.changed', {
    path: z.string(),
    version: count,
    ...changeset,
    author: z.enum(['user', 'ai', 'mcp', 'template', 'system']),
  }),
  envelope('file.deleted', { path: z.string(), ...changeset }),
  envelope('file.moved', { from: z.string(), to: z.string(), ...changeset }),
  envelope('material.ready', { path: z.string(), status: z.enum(['ready', 'failed']) }),
  envelope('build.started', { build_id: id }),
  envelope('build.finished', {
    build_id: id,
    status: z.enum(['ok', 'error', 'timeout']),
    pages: count.nullable(),
    errors_count: count,
  }),
  envelope('run.started', message),
  envelope('run.delta', { ...message, seq: count, text: z.string() }),
  envelope('run.tool_call', { ...tool, tool: z.string() }),
  envelope('run.tool_result', { ...tool, ok: z.boolean() }),
  envelope('run.finished', {
    ...run,
    status: z.enum(['done', 'failed', 'cancelled']),
    changeset_id: id,
    usage: z.object({ tokens_in: count, tokens_out: count }),
  }),
  envelope('project.locked', run),
  envelope('project.unlocked', run),
] as const;
// Проверяем данные на границе сети; публичные типы берём из OpenAPI.
const schema: z.ZodType<ProjectEvent> = z.discriminatedUnion('event', events);
const known = new Set<string>(events.map((option) => option.shape.event.value));

/** Событие из потока. null — тип, которого этот интерфейс ещё не знает: сервер мог
 * обновиться раньше вкладки, поэтому такое событие пропускаем, а не рвём поток. */
export function parseProjectEvent(event: string, id: string, data: string): ProjectEvent | null {
  if (!known.has(event)) return null;
  return schema.parse({ event, id, data: JSON.parse(data) as unknown });
}
