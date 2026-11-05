import { lazy, Suspense, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileDiff } from 'lucide-react';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import { errorMessage } from '@/app/query-client';
import { Button } from '@/components/ui/button';
import { useProjectLock } from '@/features/editor/draft-context';
import { useRevertChangeset } from './use-revert-changeset';

const ChangesetDialog = lazy(() =>
  import('./changeset-dialog').then(({ ChangesetDialog }) => ({ default: ChangesetDialog })),
);

export function ChangesetCard({ project, id }: { project: string; id: string }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const revert = useRevertChangeset(project, id);
  const locked = Boolean(useProjectLock(project));
  const query = useQuery({
    queryKey: ['changesets', id, 'diff'],
    staleTime: Infinity,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/changesets/{cid}/diff', {
        params: { path: { cid: id } },
        signal,
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать правки.');
      return data;
    },
  });
  const files = query.data?.files;
  const counts = files?.reduce(
    (total, file) => ({
      added: total.added + file.additions,
      deleted: total.deleted + file.deletions,
    }),
    { added: 0, deleted: 0 },
  );
  return (
    <div className="my-2 space-y-2 rounded-xl border border-ring/35 bg-secondary p-3">
      {files && counts ? (
        <div className="flex flex-wrap items-center gap-2">
          <FileDiff className="size-4 shrink-0 text-ring" aria-hidden="true" />
          <span className="text-sm font-semibold">
            {files.some((file) => file.kind === 'folder')
              ? 'Изменено файлов и папок'
              : 'Изменено файлов'}
            : {files.length}
          </span>
          <span
            aria-label="Добавлено строк"
            className="text-sm text-emerald-600 dark:text-emerald-300"
          >
            +{counts.added}
          </span>
          <span aria-label="Удалено строк" className="text-sm text-rose-600 dark:text-rose-300">
            −{counts.deleted}
          </span>
        </div>
      ) : query.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(query.error)}
        </p>
      ) : (
        <p role="status" className="text-sm">
          Загружаем правки…
        </p>
      )}
      {files && files.length > 0 && (
        <Button ref={trigger} size="sm" variant="outline" onClick={() => setOpen(true)}>
          Посмотреть правки
        </Button>
      )}
      {revert.isSuccess && <p className="text-sm text-muted-foreground">Правки отменены.</p>}
      {!files && query.isError && (
        <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
          Повторить загрузку
        </Button>
      )}
      {open && files && (
        <Suspense
          fallback={
            <p role="status" className="text-sm">
              Открываем сравнение…
            </p>
          }
        >
          <ChangesetDialog
            files={files}
            revert={revert}
            locked={locked}
            onClose={() => setOpen(false)}
            restoreFocus={() => trigger.current?.focus()}
          />
        </Suspense>
      )}
    </div>
  );
}
