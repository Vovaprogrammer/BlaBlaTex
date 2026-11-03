import type { QueryClient } from '@tanstack/react-query';
import type { components } from '@/api/schema';
import { isRecord } from '@/api/api-error';
import { sessionKey } from './use-session';

export async function replaceSession(
  client: QueryClient,
  session: components['schemas']['MeResponse'] | null,
) {
  await client.cancelQueries();
  client.clear();
  client.setQueryData(sessionKey, session);
}

export function returnPath(state: unknown) {
  if (
    !isRecord(state) ||
    typeof state.from !== 'string' ||
    !state.from.startsWith('/') ||
    state.from.startsWith('//')
  )
    return '/projects';
  const target = new URL(state.from, window.location.origin);
  if (
    target.origin !== window.location.origin ||
    !/^\/(projects|profile|settings)(\/|$)/.test(target.pathname)
  )
    return '/projects';
  return target.pathname + target.search + target.hash;
}
