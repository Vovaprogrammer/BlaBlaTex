import { Link, useMatch } from 'react-router';
import { cn } from '@/lib/utils';
import { useUsage } from './usage-query';

const count = new Intl.NumberFormat('ru-RU');

export function UsageIndicator() {
  const { data } = useUsage();
  const workspace = useMatch('/projects/:id');
  if (!data) return null;
  const exhausted = !data.own_key && data.tokens_used >= data.tokens_limit;
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
          : `Израсходовано сегодня: ${count.format(data.tokens_used)} из ${count.format(data.tokens_limit)} токенов. Лимит обновится в полночь по Москве.`
      }
    >
      {data.own_key
        ? 'ИИ · свой ключ'
        : `ИИ · ${count.format(data.tokens_used)} / ${count.format(data.tokens_limit)} токенов`}
      {workspace && <span className="sr-only"> (настройки в новой вкладке)</span>}
    </Link>
  );
}
