import { FolderOpen, Settings, UserRound } from 'lucide-react';
import { NavLink, Outlet } from 'react-router';
import { AppHeader } from '@/components/app-header';
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
      <AppHeader />
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
