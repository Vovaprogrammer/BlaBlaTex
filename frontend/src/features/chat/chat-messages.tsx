import { memo, useLayoutEffect, useRef, type ReactNode } from 'react';
import { MessageSquare, UserRound } from 'lucide-react';
import Markdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { BrandMark } from '@/components/brand';
import type { Message } from './chat-data';

export function ChatMessages({
  messages,
  olderCount,
  header,
  footer,
}: {
  messages: Message[];
  olderCount: number;
  header?: ReactNode;
  footer?: ReactNode;
}) {
  const list = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const previous = useRef<{ count: number; height: number } | null>(null);
  useLayoutEffect(() => {
    const node = list.current;
    if (!node) return;
    const last = previous.current;
    if (last && olderCount > last.count) node.scrollTop += node.scrollHeight - last.height;
    else if (follow.current) node.scrollTop = node.scrollHeight;
    previous.current = { count: olderCount, height: node.scrollHeight };
  });
  return (
    <div
      ref={list}
      role="region"
      aria-label="Сообщения"
      tabIndex={0}
      onScroll={(event) => {
        const node = event.currentTarget;
        follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48;
      }}
      className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain p-3 [overflow-anchor:none] lg:p-6"
    >
      {header}
      {!messages.length && !header && !footer && (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
          <MessageSquare className="size-10 text-ring" aria-hidden="true" />
          <h2 className="text-xl font-semibold">Чат с помощником</h2>
          <p className="max-w-sm text-muted-foreground">Опишите, что нужно сделать с документом.</p>
        </div>
      )}
      {messages.map((message) => (
        <MessageCard key={message.id} message={message} />
      ))}
      {footer}
    </div>
  );
}

const MessageCard = memo(function MessageCard({ message }: { message: Message }) {
  const own = message.role === 'user';
  const date = new Date(message.created_at);
  const time = Number.isNaN(date.valueOf())
    ? null
    : date.toLocaleTimeString('ru-RU', {
        hour: '2-digit',
        minute: '2-digit',
      });
  const failure = message.parts.some((part) => part.type === 'error');
  if (
    !failure &&
    message.status !== 'failed' &&
    message.status !== 'cancelled' &&
    !message.parts.some((part) => part.type === 'text')
  )
    return null;
  return (
    <article
      className={`flex min-w-0 gap-3 rounded-2xl border p-3 lg:p-4 ${own ? 'bg-secondary' : 'bg-muted/70'}`}
    >
      <div
        className="flex size-9 shrink-0 items-center justify-center rounded-full border border-ring/40 bg-primary/25 text-ring"
        aria-hidden="true"
      >
        {own ? <UserRound className="size-5" /> : <BrandMark className="size-6" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-2">
          <h3 className="font-semibold">{own ? 'Вы' : 'BlaBlaTex Agent'}</h3>
          {time && (
            <time dateTime={message.created_at} className="text-xs text-muted-foreground">
              {time}
            </time>
          )}
        </div>
        {message.parts.map((part, index) =>
          part.type === 'text' ? (
            own ? (
              <p key={index} className="whitespace-pre-wrap [overflow-wrap:anywhere]">
                {part.text}
              </p>
            ) : (
              <div
                key={index}
                className="space-y-2 text-sm leading-relaxed [overflow-wrap:anywhere] [&_a]:text-ring [&_a]:underline [&_li]:ml-5 [&_ol]:list-decimal [&_ul]:list-disc [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-card [&_pre]:p-3 [&_.katex-display]:overflow-x-auto"
              >
                <Markdown
                  skipHtml
                  remarkPlugins={[remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={{ img: ({ alt }) => <span>{alt}</span> }}
                >
                  {part.text}
                </Markdown>
              </div>
            )
          ) : part.type === 'error' ? (
            <p key={index} role="alert" className="text-destructive [overflow-wrap:anywhere]">
              {part.text}
            </p>
          ) : null,
        )}
        {message.status === 'failed' && !failure && (
          <p role="alert" className="text-destructive">
            Не удалось завершить ответ. Попробуйте отправить сообщение ещё раз.
          </p>
        )}
        {message.status === 'cancelled' && (
          <p className="text-sm text-muted-foreground">Ответ остановлен.</p>
        )}
      </div>
    </article>
  );
});
