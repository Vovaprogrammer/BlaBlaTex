import type { ReactNode } from 'react';
import { FolderOpen, Settings, UserRound } from 'lucide-react';
import { Link } from 'react-router';
import { Brand } from './brand';
import { ThemeToggle } from './theme-toggle';
import { buttonVariants } from './ui/button';
import { cn } from '@/lib/utils';

export function AppHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b bg-card px-4 py-3 sm:px-8">
      <div className="flex min-w-0 flex-1 items-center gap-4 sm:gap-7">
        <Link
          to="/projects"
          aria-label="BlaBlaTex — на главную"
          className="shrink-0 rounded-md focus-visible:outline-2 focus-visible:outline-ring"
        >
          <Brand />
        </Link>
        {children ?? (
          <Link
            to="/projects"
            className="hidden items-center gap-3 border-l pl-7 text-xl font-semibold sm:flex"
          >
            <FolderOpen className="size-6 text-ring" aria-hidden="true" />
            Проекты
          </Link>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
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
