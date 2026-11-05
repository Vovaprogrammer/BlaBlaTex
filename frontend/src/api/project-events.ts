import { fetchEventSource } from '@microsoft/fetch-event-source';
import { api } from './client';
import { ApiError } from './api-error';
import { parseProjectEvent, type ProjectEvent } from './project-event';

export type EventConnection = 'connecting' | 'connected' | 'retrying' | 'stopped';
export async function listenProjectEvents(
  project: string,
  signal: AbortSignal,
  callbacks: {
    event: (event: ProjectEvent) => void;
    connected?: () => void;
    status?: (status: EventConnection, message?: string) => void;
  },
) {
  if (signal.aborted) return true;
  let attempts = 0;
  let last = '';
  let opened = 0;
  callbacks.status?.('connecting');
  await fetchEventSource('/api/v1/projects/{pid}/events', {
    signal,
    // Фоновая вкладка тоже получает обновления и не создаёт второй цикл повторов.
    openWhenHidden: true,
    fetch: async (_url, init) => {
      const { response } = await api.GET('/api/v1/projects/{pid}/events', {
        params: { path: { pid: project } },
        headers: init?.headers,
        signal: init?.signal ?? undefined,
        parseAs: 'stream',
      });
      return response;
    },
    async onopen(response) {
      if (signal.aborted) return;
      if (!response.headers.get('Content-Type')?.startsWith('text/event-stream') || !response.body)
        throw new ApiError(
          0,
          'invalid_event_stream',
          'Сервер не прислал поток обновлений проекта.',
        );
      opened = Date.now();
      callbacks.status?.('connected');
      callbacks.connected?.();
    },
    onmessage(message) {
      if (signal.aborted || !message.data) return;
      let event: ProjectEvent | null;
      try {
        event = parseProjectEvent(message.event, message.id, message.data);
      } catch {
        throw new ApiError(0, 'invalid_event_stream', 'Не удалось прочитать обновления проекта.');
      }
      attempts = 0;
      if (!event) return;
      if (last) {
        const [time = 0n, seq = 0n] = event.id.split('-').map(BigInt);
        const [oldTime = 0n, oldSeq = 0n] = last.split('-').map(BigInt);
        if (time < oldTime || (time === oldTime && seq <= oldSeq)) return;
      }
      callbacks.event(event);
      last = event.id;
    },
    onclose() {
      throw new Error('Поток завершился');
    },
    onerror(error: unknown) {
      if (signal.aborted) throw error;
      if (
        error instanceof ApiError &&
        ((error.status >= 400 && error.status < 500 && error.status !== 429) ||
          error.code === 'invalid_event_stream')
      ) {
        callbacks.status?.('stopped', error.message);
        throw error;
      }
      if (opened && Date.now() - opened >= 30_000) attempts = 0;
      opened = 0;
      callbacks.status?.(
        'retrying',
        error instanceof ApiError
          ? error.message
          : 'Не удалось связаться с сервером. Проверьте соединение.',
      );
      return Math.min(1000 * 2 ** attempts++, 30_000);
    },
  });
  return true;
}
