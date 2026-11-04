import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { expect, test, vi } from 'vitest';
import { createQueryClient } from '@/app/query-client';
import { demoId, currentAccount } from '@/mocks/data';
import { server } from '@/test/server';
import { sessionKey } from '@/features/auth/use-session';
import { useProjectEvents } from './use-project-events';

test('смена проекта, выключение и очистка сессии отменяют старый поток', async () => {
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
  await waitFor(() => expect(signals).toHaveLength(1));
  hook.rerender({ project: 'another-project', enabled: true });
  await waitFor(() => expect(signals).toHaveLength(2));
  await waitFor(() => expect(signals[0]!.aborted).toBe(true));
  hook.rerender({ project: 'another-project', enabled: false });
  await waitFor(() => expect(signals[1]!.aborted).toBe(true));
  hook.rerender({ project: demoId, enabled: true });
  await waitFor(() => expect(signals).toHaveLength(3));
  await act(() => client.clear());
  await waitFor(() => expect(signals[2]!.aborted).toBe(true));
  hook.unmount();
  client.clear();
});
