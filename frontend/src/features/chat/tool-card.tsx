import { Check, ChevronDown, CircleAlert, LoaderCircle, Wrench } from 'lucide-react';
import type { components } from '@/api/schema';

export function ToolCard({
  part,
  active,
}: {
  part: components['schemas']['ToolPart'];
  active: boolean;
}) {
  const Icon =
    part.ok === true ? Check : part.ok === false ? CircleAlert : active ? LoaderCircle : Wrench;
  const status =
    part.ok === true
      ? 'Готово'
      : part.ok === false
        ? 'Ошибка'
        : active
          ? 'Выполняется…'
          : 'Нет результата';
  return (
    <details className="group my-2 rounded-xl border bg-secondary text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl p-3 focus-visible:outline-2 focus-visible:outline-ring">
        <Icon className="size-4 shrink-0 text-ring" aria-hidden="true" />
        <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{part.summary}</span>
        <ChevronDown className="size-4 shrink-0 group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="space-y-1 border-t px-3 py-2 [overflow-wrap:anywhere]">
        <p className="text-xs text-muted-foreground">{status}</p>
        {part.result && <p className="whitespace-pre-wrap">{part.result}</p>}
      </div>
    </details>
  );
}
