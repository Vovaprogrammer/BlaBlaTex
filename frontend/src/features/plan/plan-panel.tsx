import { ErrorState, LoadingState } from '@/components/screen-state';
import type { useReportPlan } from './plan-data';

export function PlanPanel({ query }: { query: ReturnType<typeof useReportPlan> }) {
  const plan = query.data;
  return (
    <section
      aria-labelledby="report-plan-title"
      className="min-h-0 flex-1 space-y-4 overflow-auto p-3 lg:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="report-plan-title" className="text-xl font-semibold">
          План отчёта
        </h2>
        {plan && (
          <p className="text-sm text-muted-foreground">
            {plan.status === 'confirmed' ? 'Подтверждён' : 'Черновик'}
          </p>
        )}
      </div>
      {query.isPending && <LoadingState>Загружаем план…</LoadingState>}
      {query.isError && (
        <ErrorState
          error={query.error}
          retry={() => void query.refetch()}
          retrying={query.isFetching}
        />
      )}
      {plan === null && (
        <p className="text-sm text-muted-foreground">
          План ещё не составлен. Его можно составить в чате.
        </p>
      )}
      {plan && (
        <>
          <ol aria-label="Разделы отчёта" className="space-y-3">
            {plan.plan.sections.map((section) => (
              <li key={section.section_id} className="space-y-2 rounded-xl border bg-card p-3">
                <h3 className="font-semibold">{section.title}</h3>
                {section.note && (
                  <p className="whitespace-pre-wrap break-words text-sm">{section.note}</p>
                )}
                {section.materials.length > 0 ? (
                  <MaterialPaths paths={section.materials} />
                ) : (
                  <p className="text-sm text-muted-foreground">Материалы не назначены</p>
                )}
              </li>
            ))}
          </ol>
          {plan.plan.unassigned.length > 0 && (
            <section className="space-y-2">
              <h3 className="font-semibold">Материалы вне плана</h3>
              <MaterialPaths paths={plan.plan.unassigned} />
            </section>
          )}
        </>
      )}
    </section>
  );
}

export function MaterialPaths({ paths }: { paths: string[] }) {
  return (
    <ul className="list-inside list-disc space-y-1 text-sm text-muted-foreground">
      {paths.map((path) => (
        <li key={path} className="[overflow-wrap:anywhere]" title={path}>
          {path.replace(/^materials\//, '')}
        </li>
      ))}
    </ul>
  );
}
