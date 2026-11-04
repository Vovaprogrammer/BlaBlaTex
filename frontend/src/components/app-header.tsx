import type { ReactNode } from 'react';
import { FolderOpen, Settings, UserRound } from 'lucide-react';
import { Link } from 'react-router';
import { Brand } from './brand';
import { ThemeToggle } from './theme-toggle';
import { buttonVariants } from './ui/button';
import { cn } from '@/lib/utils';
import { DraftBadge } from '@/features/editor/draft-badge';

export function AppHeader({ children, actions }: { children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 border-b bg-card px-4 py-3 sm:flex sm:gap-7 sm:px-8">
      <Link
        to="/projects"
        aria-label="BlaBlaTex — на главную"
        className="shrink-0 rounded-md focus-visible:outline-2 focus-visible:outline-ring"
      >
        <Brand />
      </Link>
      {children ? (
        <div className="col-span-2 row-start-2 min-w-0 sm:flex-1">{children}</div>
      ) : (
        <Link
          to="/projects"
          className="hidden flex-1 items-center gap-3 border-l pl-7 text-xl font-semibold sm:flex"
        >
          <FolderOpen className="size-6 text-ring" aria-hidden="true" />
          Проекты
        </Link>
      )}
      <DraftBadge />
      <div className="col-start-2 row-start-1 ml-auto flex shrink-0 items-center gap-2">
        {actions && <div className="hidden sm:block">{actions}</div>}
        <ThemeToggle />
        <Link
          to="/settings"
          aria-label="Открыть настройки"
          className={buttonVariants({ variant: 'outline', size: 'icon' })}
        >
          <Settings aria-hidden="true" />
        </Link>
        <Link
          to="/profile"
          aria-label="Открыть профиль"
          className={cn(
            buttonVariants({ variant: 'secondary', size: 'icon' }),
            'rounded-full border border-ring bg-primary text-primary-foreground',
          )}
        >
          <UserRound aria-hidden="true" />
        </Link>
      </div>
    </header>
  );
}
