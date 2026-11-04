import { RefreshCw } from 'lucide-react';
import type { EventConnection } from '@/api/project-events';
import { Button } from '@/components/ui/button';

const labels: Record<EventConnection, string> = {
  connecting: 'Подключаем обновления…',
  connected: 'Обновления подключены',
  retrying: 'Связь прервалась. Подключаемся снова…',
  stopped: 'Автообновления недоступны',
};
export function EventStatus({
  connection,
  retry,
}: {
  connection: EventConnection;
  retry: () => void;
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 border-b px-3 py-1 text-xs text-muted-foreground">
      <span role="status" className="min-w-0 break-words">
        {labels[connection]}
      </span>
      {connection === 'stopped' && (
        <Button variant="ghost" size="sm" onClick={retry} className="h-8 text-xs">
          <RefreshCw className="size-3" aria-hidden="true" />
          Подключить снова
        </Button>
      )}
    </div>
  );
}
