import { Link, useMatch } from 'react-router';
import { cn } from '@/lib/utils';
import { useUsage } from './usage-query';

const count = new Intl.NumberFormat('ru-RU');

export function UsageIndicator() {
  const { data } = useUsage();
  const workspace = useMatch('/projects/:id');
  if (!data) return null;
  const remaining = Math.max(0, data.tokens_limit - data.tokens_used);
  const percent = data.tokens_limit > 0 ? Math.min(100, (remaining / data.tokens_limit) * 100) : 0;
  const exhausted = !data.own_key && remaining === 0;
  return (
    <Link
      to="/settings#llm-key"
      target={workspace ? '_blank' : undefined}
      rel={workspace ? 'noopener' : undefined}
      className={cn(
        'col-span-2 row-start-4 justify-self-start whitespace-nowrap rounded-md border px-2 py-1 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring sm:shrink-0',
        exhausted ? 'border-destructive text-destructive' : 'text-muted-foreground',
      )}
      title={
        data.own_key
          ? 'Запросы идут через ваш ключ'
          : `Осталось ${count.format(remaining)} из ${count.format(data.tokens_limit)} токенов. Лимит обновится в полночь по Москве.`
      }
    >
      {data.own_key ? (
        'ИИ · свой ключ'
      ) : (
        <>
          <span className="block">ИИ · Осталось {count.format(remaining)} токенов</span>
          <span
            aria-hidden="true"
            className="mt-1 block h-1.5 overflow-hidden rounded-full bg-ring/20"
          >
            <span className="block h-full rounded-full bg-ring" style={{ width: `${percent}%` }} />
          </span>
        </>
      )}
      {workspace && <span className="sr-only"> (настройки в новой вкладке)</span>}
    </Link>
  );
}
