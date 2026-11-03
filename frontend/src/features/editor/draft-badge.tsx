import { Link } from 'react-router';
import { DropdownMenu } from 'radix-ui';
import { Button } from '@/components/ui/button';
import { useDraftRevision, useDraftStore } from './draft-context';

export function DraftBadge() {
  const store = useDraftStore();
  useDraftRevision();
  const pending = store.pending();
  if (!pending.length) return null;
  return (
    <div className="col-span-2 row-start-3 min-w-0 sm:ml-auto">
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <Button
            variant="outline"
            className="max-w-44 truncate"
            aria-label={`Несохранённых файлов: ${pending.length}`}
          >
            Не сохранено: {pending.length}
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            className="z-40 max-h-80 max-w-[90vw] overflow-auto rounded-xl border bg-card p-2 shadow-xl"
          >
            {pending.map((draft) => (
              <DropdownMenu.Item key={JSON.stringify([draft.project, draft.path])} asChild>
                <Link
                  to={`/projects/${encodeURIComponent(draft.project)}?file=${encodeURIComponent(draft.path)}`}
                  className="block max-w-80 truncate rounded px-3 py-2 text-sm outline-none data-[highlighted]:bg-accent"
                >
                  {draft.path}
                </Link>
              </DropdownMenu.Item>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}
