import { usePdf } from './pdf-queries';
import { FileText } from 'lucide-react';
import { EmptyState, ErrorState, LoadingState } from '@/components/screen-state';
import { PdfViewer } from './pdf-viewer';
import type { PdfPosition } from './pdf-position';

export function PdfPanel({ bid, position }: { bid?: string; position: PdfPosition }) {
  const pdf = usePdf(bid);
  if (pdf.data || pdf.isError)
    return (
      <div className="flex h-full min-h-0 flex-col">
        {pdf.isError && (
          <ErrorState
            className="m-3 shrink-0"
            error={pdf.error}
            retry={() => void pdf.refetch()}
            retrying={pdf.isFetching}
            retryLabel="Повторить загрузку PDF"
            note={pdf.data ? 'Показан ранее загруженный PDF.' : undefined}
          />
        )}
        {pdf.data && (
          <div className="min-h-0 flex-1">
            <PdfViewer blob={pdf.data} position={position} />
          </div>
        )}
      </div>
    );
  if (bid && pdf.isPending) return <LoadingState className="p-4">Загружаем PDF…</LoadingState>;
  return (
    <EmptyState className="h-full" icon={FileText} title="PDF пока нет">
      Нажмите «Собрать PDF», чтобы увидеть документ.
    </EmptyState>
  );
}
