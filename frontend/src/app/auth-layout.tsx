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
    <main className="relative isolate min-h-svh overflow-hidden dark:bg-[#151515]">
      <svg
        aria-hidden="true"
        viewBox="0 0 1920 1080"
        preserveAspectRatio="none"
        className="pointer-events-none absolute inset-0 -z-10 size-full fill-muted dark:fill-[#1a1a1c]"
      >
        <path d="M0 0H61V174H0Z M0 355H117V234H385V134H963V396H1084V616H967V792H727V894H517V1021H248V888H0Z M601 1007H930V1080H601Z" />
      </svg>
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
        <section className="mx-auto w-full max-w-xl rounded-[28px] bg-card p-7 shadow-[8px_8px_0_var(--auth-card-shadow)] [--auth-card-shadow:var(--muted)] sm:p-10 lg:shadow-[2.55vw_2.24vw_0_var(--auth-card-shadow)] min-[1800px]:translate-x-[7.35vw] min-[1800px]:max-w-[642px] dark:bg-[#25252a] dark:[--auth-card-shadow:#1e1e21]">
          <Outlet />
        </section>
      </div>
    </main>
  );
}
