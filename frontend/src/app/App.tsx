import { FolderOpen, Settings, UserRound } from 'lucide-react';
import { Link, NavLink, Outlet } from 'react-router';
import { Brand } from '@/components/brand';
import { ThemeToggle } from '@/components/theme-toggle';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { LogoutButton } from '@/features/auth/logout-button';

const sections = [
  ['/projects', 'Проекты', FolderOpen],
  ['/profile', 'Профиль', UserRound],
  ['/settings', 'Настройки', Settings],
] as const;

export function App() {
  return (
    <div className="min-h-svh">
      <header className="flex min-h-20 flex-wrap items-center justify-between gap-3 border-b bg-card px-4 py-3 sm:px-8">
        <div className="flex min-w-0 items-center gap-7">
          <Link
            to="/projects"
            aria-label="BlaBlaTex — на главную"
            className="shrink-0 rounded-md focus-visible:outline-2 focus-visible:outline-ring"
          >
            <Brand />
          </Link>
          <Link
            to="/projects"
            className="hidden items-center gap-3 border-l pl-7 text-xl font-semibold text-foreground sm:flex"
          >
            <FolderOpen className="size-6 text-ring" aria-hidden="true" />
            Проекты
          </Link>
        </div>
        <div className="flex items-center gap-2">
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
      <div className="mx-auto grid max-w-[1800px] gap-5 p-4 sm:p-8 lg:grid-cols-[260px_minmax(0,1fr)]">
        <nav
          aria-label="Разделы приложения"
          className="flex flex-wrap gap-2 rounded-2xl border bg-card p-4 lg:min-h-[calc(100svh-9rem)] lg:flex-nowrap lg:flex-col lg:justify-start lg:p-5"
        >
          {sections.map(([path, label, Icon]) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                cn(
                  'flex min-h-11 items-center gap-3 rounded-xl border border-transparent px-4 py-3 text-base font-medium focus-visible:outline-2 focus-visible:outline-ring',
                  isActive
                    ? 'border-ring bg-primary text-primary-foreground'
                    : 'text-foreground hover:bg-muted',
                )
              }
            >
              <Icon className="size-5 shrink-0" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
          <LogoutButton />
        </nav>
        <main className="min-w-0 rounded-2xl border bg-card p-6 sm:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
