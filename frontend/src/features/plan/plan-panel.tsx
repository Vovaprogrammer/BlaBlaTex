import { useState } from 'react';
import { Link } from 'react-router';
import { ErrorState, LoadingState } from '@/components/screen-state';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import type { Run } from '@/features/chat/chat-data';
import { isQuotaExceeded, type ChatActions } from '@/features/chat/use-chat-actions';
import type { useReportPlan } from './plan-data';
import { PlanEditor } from './plan-editor';

export function PlanPanel({
  id,
  query,
  active,
  locked,
  actions,
  onConfirmed,
}: {
  id: string;
  query: ReturnType<typeof useReportPlan>;
  active: Run | null;
  locked: boolean;
  actions: ChatActions;
  onConfirmed: () => void;
}) {
  const plan = query.data;
  const [editing, setEditing] = useState(false);
  const { send } = actions;
  const confirming = typeof send.variables === 'object' && send.variables.kind === 'confirm';
  const busy = locked || Boolean(active) || send.isPending || actions.uploading;

  async function confirm() {
    if (await actions.confirmPlan(active)) onConfirmed();
  }
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
      {plan && editing && (
        <PlanEditor id={id} plan={plan} locked={busy} onClose={() => setEditing(false)} />
      )}
      {plan && !editing && (
        <>
          {confirming && send.error && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(send.error)}
              {isQuotaExceeded(send.error) && (
                <>
                  {' '}
                  <Link to="/settings#llm-key" target="_blank" rel="noopener" className="underline">
                    Открыть настройки ключа ИИ (в новой вкладке)
                  </Link>
                </>
              )}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(true)}>
              Изменить план
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void confirm()}>
              {confirming && send.isPending
                ? 'Запускаем отчёт…'
                : plan.status === 'confirmed'
                  ? 'Написать отчёт заново'
                  : 'Подтвердить и написать отчёт'}
            </Button>
          </div>
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

function MaterialPaths({ paths }: { paths: string[] }) {
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
