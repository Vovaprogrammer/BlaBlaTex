import { MessageSquare } from 'lucide-react';

export function ProjectChats({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="p-4">
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-center gap-3 rounded-xl border border-ring bg-primary/30 p-3 text-left"
      >
        <MessageSquare className="size-5 shrink-0 text-ring" aria-hidden="true" />
        Чат проекта
      </button>
    </div>
  );
}
