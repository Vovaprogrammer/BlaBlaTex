import { http, HttpResponse } from 'msw';
import { mockState, ownedProject, type Schemas } from './data';
import { failure, guard, invalid, readBody, validText } from './responses';
import { emitMockEvent } from './project-events';
import { addExampleChangeset } from './changeset-handlers';

type Chat = { items: Schemas['ChatMessageOut'][]; run: Schemas['RunOut'] | null };
const chats = new WeakMap<typeof mockState.current, Map<string, Chat>>();
function getChat(id: string) {
  let projects = chats.get(mockState.current);
  if (!projects) chats.set(mockState.current, (projects = new Map()));
  let chat = projects.get(id);
  if (!chat) projects.set(id, (chat = { items: [], run: null }));
  return chat;
}

function finish(id: string, run: Schemas['RunOut'], status: 'done' | 'cancelled') {
  run.status = status;
  run.finished_at = new Date().toISOString();
  const reply = getChat(id).items.find((item) => item.id === run.message_id);
  if (reply) reply.status = status;
  emitMockEvent(id, {
    event: 'run.finished',
    data: {
      run_id: run.id,
      changeset_id: run.changeset_id,
      status,
      usage: { tokens_in: 0, tokens_out: 0 },
    },
  });
}

function streamReply(
  id: string,
  run: Schemas['RunOut'],
  reply: Schemas['ChatMessageOut'],
  example: boolean,
) {
  const state = mockState.current;
  setTimeout(() => {
    if (state !== mockState.current || run.status !== 'queued') return;
    run.status = reply.status = 'running';
    emitMockEvent(id, { event: 'run.started', data: { run_id: run.id, message_id: reply.id } });
    const chunks = [
      '**Пример ответа BlaBlaTex.** Это демонстрация чата.\n\n',
      'Для раздела «Результаты» можно описать ход эксперимента и сравнить измерения.\n\n',
      'Среднее значение вычисляется так:\n\n$$\n\\bar{x} = \\frac{1}{n} \\sum_{i=1}^{n} x_i\n$$\n\n',
      '1. Укажите условия эксперимента.\n2. Добавьте таблицу измерений.\n3. Сформулируйте вывод по данным.',
    ];
    chunks.forEach((text, index) =>
      setTimeout(
        () => {
          if (state !== mockState.current || run.status !== 'running') return;
          const part = reply.parts[0];
          reply.parts = [{ type: 'text', text: (part?.type === 'text' ? part.text : '') + text }];
          emitMockEvent(id, {
            event: 'run.delta',
            data: { run_id: run.id, message_id: reply.id, seq: ++reply.seq, text },
          });
          if (index === chunks.length - 1) {
            if (example && addExampleChangeset(id, run)) {
              const tool = {
                run_id: run.id,
                call_id: 'example-files',
                tool: 'write_file',
                summary: 'Добавлены разделы отчёта',
              };
              const result = 'Созданы results.tex и conclusion.tex.';
              emitMockEvent(id, { event: 'run.tool_call', data: { ...tool, seq: ++reply.seq } });
              emitMockEvent(id, {
                event: 'run.tool_result',
                data: {
                  run_id: run.id,
                  call_id: tool.call_id,
                  summary: result,
                  ok: true,
                  seq: ++reply.seq,
                },
              });
              reply.parts.push(
                {
                  type: 'tool',
                  tool: tool.tool,
                  call_id: tool.call_id,
                  summary: tool.summary,
                  result,
                  ok: true,
                },
                { type: 'changeset', changeset_id: run.changeset_id },
              );
            }
            finish(id, run, 'done');
          }
        },
        300 + index * 1150,
      ),
    );
  }, 500);
}

export const chatHandlers = [
  http.get('/api/v1/projects/:pid/messages', ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    const id = String(params.pid);
    if (!ownedProject(id)) return failure(404, 'not_found', 'Проект не найден');
    const { items, run } = getChat(id);
    const active_run = run && (run.status === 'queued' || run.status === 'running') ? run : null;
    const query = new URL(request.url).searchParams;
    const before = query.get('before');
    const limit = Number(query.get('limit') ?? 50);
    const end = before ? items.findIndex((message) => message.id === before) : items.length;
    if (end < 0 || !Number.isInteger(limit) || limit < 1 || limit > 100) return invalid('before');
    const start = Math.max(0, end - limit);
    return HttpResponse.json<Schemas['MessageList']>({
      items: items.slice(start, end),
      has_more: start > 0,
      active_run,
    });
  }),
  http.post('/api/v1/projects/:pid/messages', async ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    const id = String(params.pid);
    if (!ownedProject(id)) return failure(404, 'not_found', 'Проект не найден');
    const { text } = await readBody(request);
    if (!validText(text, 10_000) || !text.trim()) return invalid('text');
    const chat = getChat(id);
    if (chat.run && ['queued', 'running'].includes(chat.run.status))
      return failure(423, 'project_locked', 'Помощник уже работает.', { run_id: chat.run.id });
    const created_at = new Date().toISOString();
    const run: Schemas['RunOut'] = {
      id: crypto.randomUUID(),
      status: 'queued',
      message_id: crypto.randomUUID(),
      changeset_id: crypto.randomUUID(),
      created_at,
      finished_at: null,
      error: null,
    };
    const message: Schemas['ChatMessageOut'] = {
      id: crypto.randomUUID(),
      role: 'user',
      run_id: run.id,
      status: null,
      parts: [{ type: 'text', text: text.trim() }],
      seq: 0,
      created_at,
    };
    const reply: Schemas['ChatMessageOut'] = {
      id: run.message_id,
      role: 'assistant',
      run_id: run.id,
      status: 'queued',
      parts: [],
      seq: 0,
      created_at,
    };
    chat.items.push(message, reply);
    chat.run = run;
    streamReply(id, run, reply, text.trim() === 'Покажи пример правок');
    return HttpResponse.json<Schemas['MessageCreated']>({ message, run }, { status: 201 });
  }),
  http.post('/api/v1/runs/:rid/cancel', ({ request, params }) => {
    const error = guard(request);
    if (error) return error;
    for (const [id, chat] of chats.get(mockState.current) ?? []) {
      if (!ownedProject(id) || chat.run?.id !== params.rid || !chat.run) continue;
      if (chat.run.status === 'queued' || chat.run.status === 'running')
        finish(id, chat.run, 'cancelled');
      return HttpResponse.json(chat.run);
    }
    return failure(404, 'not_found', 'Ответ не найден');
  }),
];
