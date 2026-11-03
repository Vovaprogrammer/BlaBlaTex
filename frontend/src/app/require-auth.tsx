import { LoaderCircle } from 'lucide-react';
import { Navigate, Outlet, useLocation } from 'react-router';
import { useSession } from '@/features/auth/use-session';
import { Button } from '@/components/ui/button';
import { Brand } from '@/components/brand';
import { errorMessage } from './query-client';

export function RequireAuth() {
  const session = useSession();
  const location = useLocation();
  if (session.isPending)
    return (
      <main role="status" className="flex min-h-svh items-center justify-center gap-3">
        <LoaderCircle className="size-5 motion-safe:animate-spin" aria-hidden="true" />
        Проверяем вход…
      </main>
    );
  if (session.isError)
    return (
      <main role="alert" className="mx-auto max-w-xl space-y-6 px-6 py-20">
        <Brand />
        <h1 className="text-2xl font-semibold">Не удалось проверить вход</h1>
        <p className="text-muted-foreground">{errorMessage(session.error)}</p>
        <Button onClick={() => void session.refetch()}>Повторить</Button>
      </main>
    );
  if (!session.data)
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search + location.hash }}
      />
    );
  return <Outlet />;
}
