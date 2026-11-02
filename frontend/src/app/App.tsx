import { FlaskConical } from 'lucide-react';
import { ThemeToggle } from '@/components/theme-toggle';

export function App() {
  return (
    <div className="min-h-svh">
      <header className="flex min-h-20 items-center justify-between gap-4 border-b bg-card px-5 sm:px-10">
        <span className="flex items-center gap-3 text-2xl font-bold tracking-tight">
          <FlaskConical className="size-9 text-ring" aria-hidden="true" />
          BlaBlaTex
        </span>
        <ThemeToggle />
      </header>
      <main className="mx-auto max-w-5xl px-5 py-16 sm:px-10">
        <section className="rounded-2xl border bg-card p-8 sm:p-12">
          <h1 className="text-3xl font-semibold">Ваши проекты</h1>
          <p className="mt-3 text-muted-foreground">
            Здесь будут ваши отчёты по шаблонам дисциплин.
          </p>
        </section>
      </main>
    </div>
  );
}
