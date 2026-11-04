import { useLatestBuild, usePdf } from './pdf-queries';
import { PdfViewer } from './pdf-viewer';
import type { PdfPosition } from './pdf-position';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';

export function PdfPanel({ id, position }: { id: string; position: PdfPosition }) {
  const latest = useLatestBuild(id);
  const pdf = usePdf(latest.data?.has_pdf ? latest.data.id : undefined);
  if (latest.isError || pdf.isError)
    return (
      <div role="alert" className="space-y-3 p-4">
        <p>{errorMessage(latest.error ?? pdf.error)}</p>
        <Button onClick={() => void (latest.isError ? latest.refetch() : pdf.refetch())}>
          Повторить загрузку PDF
        </Button>
      </div>
    );
  if (latest.isPending || (latest.data?.has_pdf && pdf.isPending))
    return (
      <p role="status" className="p-4">
        Загружаем PDF…
      </p>
    );
  if (!pdf.data)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        PDF пока нет. Здесь появится результат сборки документа.
      </p>
    );
  return <PdfViewer blob={pdf.data} position={position} />;
}
