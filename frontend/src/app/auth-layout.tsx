import { BookOpen, FileText, WandSparkles } from 'lucide-react';
import { Link, Outlet } from 'react-router';
import { Brand } from '@/components/brand';
import { ThemeToggle } from '@/components/theme-toggle';

const features = [
  [WandSparkles, 'Отчёты по материалам'],
  [FileText, 'Таблицы, графики, диаграммы'],
  [BookOpen, 'Оформление по шаблону'],
] as const;

export function AuthLayout() {
  return (
    <main className="relative isolate min-h-svh overflow-hidden">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-24 top-1/4 -z-10 h-2/3 w-3/5 bg-foreground/[0.02]"
      />
      <div className="absolute right-5 top-5">
        <ThemeToggle />
      </div>
      <div className="mx-auto grid min-h-svh max-w-[1560px] items-center gap-12 px-6 py-24 sm:px-10 lg:grid-cols-2 lg:gap-20 lg:px-20">
        <section className="mx-auto w-full max-w-xl">
          <Link
            to="/"
            aria-label="BlaBlaTex — на главную"
            className="inline-block rounded-md focus-visible:outline-2 focus-visible:outline-ring"
          >
            <Brand large />
          </Link>
          <p className="mt-3 text-xl font-medium">Начните создавать документы</p>
          <ul className="mt-14 hidden space-y-7 lg:block">
            {features.map(([Icon, label]) => (
              <li key={label} className="flex items-center gap-5 text-xl font-medium">
                <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-muted">
                  <Icon className="size-6 text-ring" aria-hidden="true" />
                </span>
                {label}
              </li>
            ))}
          </ul>
        </section>
        <section className="mx-auto w-full max-w-xl rounded-[28px] bg-card p-7 shadow-[18px_20px_0_var(--muted)] sm:p-10">
          <Outlet />
        </section>
      </div>
    </main>
  );
}
