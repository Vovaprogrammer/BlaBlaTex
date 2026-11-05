import { LoaderCircle } from 'lucide-react';
import { errorMessage } from '@/app/query-client';
import { Button } from '@/components/ui/button';
import { ChatComposer } from './chat-composer';
import { ChatMessages } from './chat-messages';
import type { useChatData } from './chat-data';
import type { ChatActions } from './use-chat-actions';
import type { useOlderMessages } from './use-older-messages';

export function ProjectChat({
  project,
  chat,
  actions,
  older,
}: {
  project: string;
  chat: ReturnType<typeof useChatData>;
  actions: ChatActions;
  older: ReturnType<typeof useOlderMessages>;
}) {
  const { history, refresh } = chat;
  const active = history.data?.active_run ?? null;
  const compiling = chat.messages
    .find((message) => message.id === active?.message_id)
    ?.parts.some((part) => part.type === 'tool' && part.tool === 'compile' && part.ok == null);
  return (
    <section aria-label="Чат с помощником" className="flex h-full min-h-0 flex-col">
      <ChatMessages
        project={project}
        messages={older.messages}
        olderCount={older.olderCount}
        header={
          history.isError ? (
            <div className="space-y-2">
              <p role="alert">{errorMessage(history.error)}</p>
              <Button variant="outline" onClick={refresh}>
                Обновить переписку
              </Button>
            </div>
          ) : history.isPending ? (
            <p role="status">Загружаем переписку…</p>
          ) : older.hasMore ? (
            <div className="space-y-2 text-center">
              <Button variant="outline" disabled={older.loading} onClick={older.loadMore}>
                {older.loading ? 'Загружаем…' : 'Показать более ранние сообщения'}
              </Button>
              {older.error && (
                <p role="alert" className="text-sm text-destructive">
                  {errorMessage(older.error)}
                </p>
              )}
            </div>
          ) : undefined
        }
        footer={
          active && (
            <p role="status" className="flex items-center gap-2 px-2 text-sm text-muted-foreground">
              <LoaderCircle aria-hidden="true" className="size-4 motion-safe:animate-spin" />
              {actions.stopping === active.id || actions.cancel.isPending
                ? 'Останавливаем ответ…'
                : compiling
                  ? 'Собирает PDF…'
                  : active.status === 'queued'
                    ? 'Ответ в очереди…'
                    : 'Думает…'}
            </p>
          )
        }
      />
      <ChatComposer actions={actions} active={active} unavailable={!history.data} />
    </section>
  );
}
