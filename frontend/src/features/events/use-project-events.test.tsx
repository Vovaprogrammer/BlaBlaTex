import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { expect, onTestFinished, test, vi } from 'vitest';
import { createQueryClient } from '@/app/query-client';
import { demoId, currentAccount } from '@/mocks/data';
import { server } from '@/test/server';
import { sessionKey } from '@/features/auth/use-session';
import { useProjectEvents } from './use-project-events';

const ABORT_TIMEOUT = 5_000;

async function renderEvents() {
  const signals: AbortSignal[] = [];
  server.use(
    http.get('/api/v1/projects/:pid/events', ({ request }) => {
      signals.push(request.signal);
      return new HttpResponse(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(': keep-alive\n\n'));
            request.signal.addEventListener('abort', () => controller.close(), { once: true });
          },
        }),
        { headers: { 'Content-Type': 'text/event-stream' } },
      );
    }),
  );
  const client = createQueryClient(vi.fn());
  const account = currentAccount()!;
  client.setQueryData(sessionKey, { user: account.user, profile: account.profile });
  const hook = renderHook(
    ({ project, enabled }) => useProjectEvents(project, enabled, { event: vi.fn() }),
    {
      initialProps: { project: demoId, enabled: true },
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  onTestFinished(() => {
    hook.unmount();
    client.clear();
  });
  await waitFor(() => expect(signals).toHaveLength(1));
  return { client, hook, signals };
}

async function expectAborted(signal: AbortSignal) {
  // Отмена проходит через TanStack Query и MSW, поэтому на медленном CI нужен запас времени.
  await waitFor(() => expect(signal.aborted).toBe(true), { timeout: ABORT_TIMEOUT });
}

test('смена проекта отменяет старый поток и создаёт новый', async () => {
  const { hook, signals } = await renderEvents();
  hook.rerender({ project: 'another-project', enabled: true });
  await waitFor(() => expect(signals).toHaveLength(2));
  await expectAborted(signals[0]!);
  expect(signals[1]!.aborted).toBe(false);
});

test('выключение отменяет поток, а повторное включение создаёт новый', async () => {
  const { hook, signals } = await renderEvents();
  hook.rerender({ project: demoId, enabled: false });
  await expectAborted(signals[0]!);
  hook.rerender({ project: demoId, enabled: true });
  await waitFor(() => expect(signals).toHaveLength(2));
  expect(signals[1]!.aborted).toBe(false);
});

test('очистка сессии отменяет поток', async () => {
  const { client, signals } = await renderEvents();
  await act(() => client.clear());
  await expectAborted(signals[0]!);
});
