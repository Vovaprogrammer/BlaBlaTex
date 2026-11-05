import { useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { ProjectEvent } from '@/api/project-event';
import type { components } from '@/api/schema';

type Schemas = components['schemas'];
export type Message = Schemas['ChatMessageOut'];
export type Run = Schemas['RunOut'];
type Piece = Extract<ProjectEvent, { event: 'run.delta' | 'run.tool_call' | 'run.tool_result' }>;
type Stream = {
  runId: string;
  messageId?: string;
  startedAt?: string;
  pieces: Piece[];
};

export const chatKey = (id: string) => ['projects', id, 'messages'] as const;

export async function postChatMessage(id: string, text: string) {
  const { data } = await api.POST('/api/v1/projects/{pid}/messages', {
    params: { path: { pid: id } },
    body: { text },
  });
  if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил отправку сообщения.');
  return data;
}

export async function getMessages(id: string, signal: AbortSignal, before?: string) {
  const { data } = await api.GET('/api/v1/projects/{pid}/messages', {
    params: { path: { pid: id }, query: { before } },
    signal,
  });
  if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать переписку.');
  return data;
}

function applyPieces(message: Message, pieces: Piece[]): Message {
  if (message.status !== 'running' && message.status !== 'queued') return message;
  let seq = message.seq;
  const parts = [...message.parts];
  for (const piece of pieces) {
    const data = piece.data;
    if (data.seq <= seq) continue;
    if (data.seq !== seq + 1) break;
    if (piece.event === 'run.delta') {
      const last = parts.at(-1);
      const text = piece.data.text;
      if (last?.type === 'text') parts[parts.length - 1] = { type: 'text', text: last.text + text };
      else parts.push({ type: 'text', text });
    } else if (piece.event === 'run.tool_call') {
      const { call_id, tool, summary } = piece.data;
      parts.push({ type: 'tool', call_id, tool, summary, ok: null, result: null });
    } else {
      const { call_id, ok, summary } = piece.data;
      for (let index = parts.length - 1; index >= 0; index--) {
        const part = parts[index];
        if (part?.type !== 'tool' || part.call_id !== call_id || part.ok != null) continue;
        parts[index] = { ...part, ok, result: summary };
        break;
      }
    }
    seq = data.seq;
  }
  return seq === message.seq ? message : { ...message, parts, seq };
}

export function useChatData(id: string, enabled: boolean) {
  const client = useQueryClient();
  const queryKey = chatKey(id);
  const history = useQuery({
    queryKey,
    queryFn: ({ signal }) => getMessages(id, signal),
    enabled,
    // Подхватываем сохранённый прогресс, даже если часть событий пропала.
    refetchInterval: (query) => (query.state.data?.active_run ? 5000 : false),
  });
  const [stream, setStream] = useState<Stream>();
  const lastPiece = useRef<{ runId: string; seq: number } | undefined>(undefined);

  function refresh() {
    void client.invalidateQueries({ queryKey, exact: true });
  }

  function event(event: ProjectEvent) {
    if (event.event === 'run.started') {
      const { run_id: runId, message_id: messageId } = event.data;
      const startedAt = new Date().toISOString();
      setStream((old) => ({
        runId,
        messageId,
        startedAt,
        pieces: old?.runId === runId ? old.pieces : [],
      }));
      refresh();
    } else if (
      event.event === 'run.delta' ||
      event.event === 'run.tool_call' ||
      event.event === 'run.tool_result'
    ) {
      const runId = event.data.run_id;
      const messageId = event.event === 'run.delta' ? event.data.message_id : undefined;
      const snapshot = client
        .getQueryData<Schemas['MessageList']>(queryKey)
        ?.items.find((item) => item.role === 'assistant' && item.run_id === runId);
      if (snapshot && snapshot.status !== 'queued' && snapshot.status !== 'running') return;
      const previous = lastPiece.current?.runId === runId ? lastPiece.current.seq : undefined;
      if (event.data.seq <= Math.max(snapshot?.seq ?? 0, previous ?? 0)) return;
      if (event.data.seq > Math.max(snapshot?.seq ?? 0, previous ?? 0) + 1) refresh();
      lastPiece.current = { runId, seq: event.data.seq };
      setStream((old) => {
        const same = old?.runId === runId ? old : undefined;
        if ((same?.pieces.at(-1)?.data.seq ?? 0) >= event.data.seq) return old;
        return {
          runId,
          messageId: messageId ?? same?.messageId ?? snapshot?.id,
          startedAt: same?.startedAt,
          pieces: [
            ...(same?.pieces.filter((piece) => piece.data.seq > (snapshot?.seq ?? 0)) ?? []),
            event,
          ],
        };
      });
    } else if (event.event === 'run.finished') {
      // Итоговое сообщение читаем из базы, включая ошибку и итоговые части.
      void client.cancelQueries({ queryKey, exact: true }).then(refresh);
    }
  }

  const messages = useMemo(() => {
    const items = history.data?.items ?? [];
    if (!stream) return items;
    const assistant = items.find(
      (item) => item.role === 'assistant' && item.run_id === stream.runId,
    );
    if (assistant)
      return items.map((item) => (item === assistant ? applyPieces(item, stream.pieces) : item));
    return stream.messageId && stream.startedAt && history.data?.active_run?.id === stream.runId
      ? [
          ...items,
          applyPieces(
            {
              id: stream.messageId,
              run_id: stream.runId,
              role: 'assistant',
              status: 'running',
              seq: 0,
              created_at: stream.startedAt,
              parts: [],
            },
            stream.pieces,
          ),
        ]
      : items;
  }, [history.data, stream]);
  return { history, messages, event, refresh };
}
