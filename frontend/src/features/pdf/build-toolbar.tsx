import { Play, RotateCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import { useDraftRevision, useDraftStore } from '@/features/editor/draft-context';
import { usePdf } from './pdf-queries';
import type { BuildController } from './use-build';
import { PdfDownload } from './pdf-download';

const labels = {
  queued: 'В очереди',
  running: 'Собираем документ…',
  ok: 'Документ собран',
  error: 'Не удалось собрать документ',
  timeout: 'Время сборки истекло',
};
export function BuildToolbar({ id, controller }: { id: string; controller: BuildController }) {
  const drafts = useDraftStore();
  useDraftRevision();
  const unsettled = drafts.pending().filter((draft) => draft.project === id);
  const blocked = unsettled.some((draft) => !['dirty', 'saving'].includes(draft.status));
  const pdf = usePdf(controller.shownPdf?.id);
  const failure = controller.start.error ?? controller.current.error ?? controller.latest.error;
  return (
    <div className="space-y-2 border-b p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={
            controller.busy ||
            blocked ||
            controller.latest.isPending ||
            controller.latest.isError ||
            controller.current.isError
          }
          onClick={() => controller.start.mutate()}
        >
          <Play className="size-4" />
          {controller.busy ? 'Сборка…' : 'Собрать PDF'}
        </Button>
        <PdfDownload bid={controller.shownPdf?.id} />
        <Button
          variant="ghost"
          size="icon"
          aria-label="Обновить состояние сборки"
          disabled={controller.start.isPending}
          onClick={() =>
            void (controller.current.isError || controller.active
              ? controller.current.refetch()
              : controller.latest.refetch())
          }
        >
          <RotateCw />
        </Button>
      </div>
      <p role="status" className="text-sm text-muted-foreground">
        {controller.start.isPending
          ? 'Сохраняем правки и запускаем сборку…'
          : controller.active
            ? labels[controller.active.status]
            : controller.latest.isPending
              ? 'Проверяем сборку…'
              : 'Сборок пока нет'}
      </p>
      {blocked && (
        <p className="text-sm text-destructive">Сначала сохраните файлы или разрешите конфликт.</p>
      )}
      {controller.shownPdf && controller.active?.id !== controller.shownPdf.id && (
        <p className="text-xs text-muted-foreground">Показан PDF предыдущей сборки.</p>
      )}
      {import.meta.env.VITE_USE_MOCKS === '1' && (
        <p className="text-xs text-muted-foreground">
          Тестовый режим: PDF — заранее подготовленный пример, компиляция не выполняется.
        </p>
      )}
      {failure && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(failure)}
        </p>
      )}
      {pdf.isError && (
        <Button variant="outline" onClick={() => void pdf.refetch()}>
          Повторить загрузку PDF
        </Button>
      )}
    </div>
  );
}
