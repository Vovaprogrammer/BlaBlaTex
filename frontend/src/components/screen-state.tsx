import type { ReactNode } from 'react';
import { CircleAlert, LoaderCircle, type LucideIcon } from 'lucide-react';
import { errorMessage } from '@/app/query-client';
import { cn } from '@/lib/utils';
import { Button } from './ui/button';

export function LoadingState({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      role="status"
      className={cn('flex items-center gap-2 text-sm text-muted-foreground', className)}
    >
      <LoaderCircle className="size-4 shrink-0 motion-safe:animate-spin" aria-hidden="true" />
      {children}
    </p>
  );
}

export function ErrorState({
  error,
  retry,
  retryLabel = 'Повторить загрузку',
  retrying,
  note,
  className,
}: {
  error: unknown;
  retry: () => void;
  retryLabel?: string;
  retrying: boolean;
  note?: string;
  className?: string;
}) {
  return (
    <div className={cn('space-y-2 rounded-lg border bg-card p-3 text-sm', className)}>
      <p role="alert" className="flex items-start gap-2 text-destructive">
        <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span className="[overflow-wrap:anywhere]">
          {errorMessage(error)}
          {note && ` ${note}`}
        </span>
      </p>
      <Button variant="outline" size="sm" disabled={retrying} onClick={retry}>
        {retrying ? 'Повторяем…' : retryLabel}
      </Button>
      {retrying && (
        <span role="status" className="sr-only">
          Повторяем загрузку…
        </span>
      )}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  className,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex min-h-0 flex-col items-center justify-center gap-3 p-4 text-center',
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-10 shrink-0 text-ring" />
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{children}</p>
    </div>
  );
}
