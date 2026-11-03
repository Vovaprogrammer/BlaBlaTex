import { FileText, MessageSquare, Paperclip, Send, Sparkles } from 'lucide-react';

export function ChatPlaceholder() {
  return (
    <section
      aria-label="Чат с помощником"
      className="flex h-full min-h-0 flex-col gap-4 p-4 lg:p-6"
    >
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 overflow-auto text-center">
        <Sparkles className="size-12 text-ring" aria-hidden="true" />
        <h2 className="text-xl font-semibold">Чат с помощником</h2>
        <p className="max-w-sm text-muted-foreground">
          Помощник скоро появится здесь. Пока можно работать с файлами проекта.
        </p>
      </div>
      <div className="space-y-5 rounded-2xl border bg-secondary p-4 text-muted-foreground">
        <p>Чат пока недоступен</p>
        <div className="flex items-center justify-between">
          <Paperclip aria-hidden="true" />
          <span className="flex size-10 items-center justify-center rounded-xl bg-primary/50">
            <Send aria-hidden="true" />
          </span>
        </div>
      </div>
    </section>
  );
}

export function PdfPlaceholder() {
  return (
    <div className="flex h-full flex-col">
      <section
        aria-label="Предпросмотр PDF"
        className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 overflow-auto p-6 text-center"
      >
        <FileText className="size-12 text-ring" aria-hidden="true" />
        <h2 className="text-xl font-semibold">Предпросмотр PDF</h2>
        <p className="text-muted-foreground">Просмотр и сборка документа скоро станут доступны.</p>
      </section>
    </div>
  );
}

export function ProjectChats({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="space-y-4 p-4">
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-center gap-3 rounded-xl border border-ring bg-primary/30 p-3 text-left"
      >
        <MessageSquare className="size-5 shrink-0 text-ring" aria-hidden="true" />
        Чат проекта
      </button>
      <p className="text-sm text-muted-foreground">Переписка с помощником пока недоступна.</p>
    </div>
  );
}
