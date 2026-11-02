import { FlaskConical, Settings, UserRound } from 'lucide-react';
import { Link, NavLink, Outlet } from 'react-router';
import { ThemeToggle } from '@/components/theme-toggle';
import { buttonVariants } from '@/components/ui/button';

const sections = [
  ['/projects', 'Проекты'],
  ['/login', 'Вход'],
  ['/register', 'Регистрация'],
  ['/profile', 'Профиль'],
  ['/settings', 'Настройки'],
] as const;

export function App() {
  return (
    <div className="min-h-svh">
      <header className="flex min-h-20 items-center justify-between gap-2 border-b bg-card px-4 sm:gap-4 sm:px-10">
        <Link
          to="/projects"
          className="flex items-center gap-2 rounded-md text-xl font-bold tracking-tight focus-visible:outline-2 focus-visible:outline-ring sm:gap-3 sm:text-2xl"
        >
          <FlaskConical className="size-8 text-ring sm:size-9" aria-hidden="true" />
          BlaBlaTex
        </Link>
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
            className={buttonVariants({ variant: 'secondary', size: 'icon' })}
          >
            <UserRound aria-hidden="true" />
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-5 py-10 sm:px-10">
        <nav aria-label="Разделы приложения" className="mb-8 flex flex-wrap gap-2">
          {sections.map(([path, label]) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                buttonVariants({ variant: isActive ? 'default' : 'secondary' })
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <Outlet />
      </main>
    </div>
  );
}
