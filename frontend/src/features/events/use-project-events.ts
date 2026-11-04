import { useEffect, useEffectEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { listenProjectEvents, type EventConnection } from '@/api/project-events';
import type { ProjectEvent } from '@/api/project-event';
import { useSession } from '@/features/auth/use-session';

export function useProjectEvents(
  project: string,
  enabled: boolean,
  callbacks: {
    event: (event: ProjectEvent) => void;
    connected?: () => void;
    status?: (status: EventConnection) => void;
  },
) {
  const client = useQueryClient();
  const { data: session } = useSession();
  const owner = session?.user.id;
  const event = useEffectEvent(callbacks.event);
  const connected = useEffectEvent(() => callbacks.connected?.());
  const status = useEffectEvent((value: EventConnection) => callbacks.status?.(value));
  useEffect(() => {
    if (!enabled || !owner) return;
    const queryKey = ['projects', project, 'events', owner];
    // QueryClient отменяет поток при очистке сессии и обрабатывает 401 как у REST.
    void client
      .fetchQuery({
        queryKey,
        queryFn: ({ signal }) => listenProjectEvents(project, signal, { event, connected, status }),
        retry: false,
        staleTime: 0,
        gcTime: 0,
      })
      .catch(() => {
        /* Ошибку показывает общий обработчик QueryCache. */
      });
    return () => {
      void client.cancelQueries({ queryKey, exact: true });
    };
  }, [client, project, enabled, owner]);
}
