import { useRef, useState } from 'react';
import { Paperclip, Send, Square, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import { materialAccept } from '@/features/materials/use-material-upload';
import type { Run } from './chat-data';
import type { ChatActions } from './use-chat-actions';

export function ChatComposer({
  actions,
  active,
  unavailable,
}: {
  actions: ChatActions;
  active: Run | null;
  unavailable: boolean;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const { text, paths, uploading, upload, send, cancel } = actions;
  const sending = send.isPending;
  const attachDisabled = sending || upload.isPending || Boolean(active) || unavailable;
  const stopping = cancel.isPending || Boolean(active && actions.stopping === active.id);
  return (
    <form
      className={`mx-3 mb-3 shrink-0 space-y-2 rounded-2xl border bg-secondary p-3 lg:mx-5 lg:mb-5 ${dragging ? 'border-ring' : ''}`}
      aria-label="Написать сообщение"
      onSubmit={(event) => {
        event.preventDefault();
        if (!unavailable) void actions.submit(active);
      }}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes('Files')) return;
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = attachDisabled ? 'none' : 'copy';
        if (!attachDisabled) setDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event) => {
        if (!event.dataTransfer.types.includes('Files')) return;
        event.preventDefault();
        event.stopPropagation();
        setDragging(false);
        if (!attachDisabled) void actions.attach(Array.from(event.dataTransfer.files));
      }}
    >
      {paths.length > 0 && (
        <ul
          aria-label="Прикреплённые материалы"
          className="flex max-h-24 flex-wrap gap-2 overflow-auto"
        >
          {paths.map((path) => (
            <li
              key={path}
              className="flex min-w-0 max-w-full items-center gap-2 rounded-lg border bg-card px-2 text-xs"
            >
              <span className="truncate" title={path}>
                {path.replace(/^materials\//, '')}
              </span>
              <button
                type="button"
                aria-label={`Убрать из сообщения: ${path}`}
                title="Убрать из сообщения. Файл останется в материалах проекта."
                className="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                disabled={sending}
                onClick={() => actions.remove(path)}
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <textarea
        aria-label="Сообщение"
        placeholder="Опишите, что нужно изменить в документе…"
        value={text}
        readOnly={sending}
        rows={2}
        className="block w-full resize-none rounded-lg bg-transparent p-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onChange={(event) => actions.setText(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (
            event.key !== 'Enter' ||
            event.shiftKey ||
            event.nativeEvent.isComposing ||
            event.keyCode === 229
          )
            return;
          event.preventDefault();
          if (!unavailable) void actions.submit(active);
        }}
        onPaste={(event) => {
          if (!event.clipboardData.files.length) return;
          event.preventDefault();
          if (!attachDisabled) void actions.attach(Array.from(event.clipboardData.files));
        }}
      />
      {uploading && (
        <p role="status" className="text-xs text-muted-foreground">
          {upload.progress.checking
            ? 'Проверяем файлы…'
            : upload.progress.percent === null
              ? 'Загружаем файлы…'
              : `Загружаем файлы: ${upload.progress.percent}%`}
        </p>
      )}
      {[actions.uploadError, send.error, cancel.error].map((error, index) =>
        error ? (
          <p key={index} role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">
            {errorMessage(error)}
          </p>
        ) : null,
      )}
      {actions.tooLong && (
        <p className="text-sm text-destructive">
          Сократите сообщение до 10 000 символов, включая имена файлов.
        </p>
      )}
      <div className="flex items-center justify-between gap-2">
        <input
          ref={picker}
          type="file"
          multiple
          accept={materialAccept}
          hidden
          onChange={(event) => {
            if (!attachDisabled) void actions.attach(Array.from(event.currentTarget.files ?? []));
            event.currentTarget.value = '';
          }}
        />
        <Button
          type="button"
          size="icon"
          variant="outline"
          aria-label="Прикрепить файлы"
          title="Прикрепить файлы в «Материалы»"
          disabled={attachDisabled}
          onClick={() => picker.current?.click()}
        >
          <Paperclip aria-hidden="true" />
        </Button>
        {active ? (
          <Button
            type="button"
            variant="outline"
            disabled={stopping}
            onClick={() => cancel.mutate(active.id)}
          >
            <Square aria-hidden="true" /> {stopping ? 'Останавливаем…' : 'Остановить'}
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            aria-label="Отправить"
            title="Отправить"
            disabled={
              unavailable ||
              sending ||
              uploading ||
              actions.tooLong ||
              (!text.trim() && !paths.length)
            }
          >
            <Send aria-hidden="true" />
          </Button>
        )}
      </div>
    </form>
  );
}
