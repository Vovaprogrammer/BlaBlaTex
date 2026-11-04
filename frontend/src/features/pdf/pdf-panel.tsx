import { usePdf } from './pdf-queries';
import { PdfViewer } from './pdf-viewer';
import type { PdfPosition } from './pdf-position';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';

export function PdfPanel({ bid, position }: { bid?: string; position: PdfPosition }) {
  const pdf = usePdf(bid);
  if (pdf.isError)
    return (
      <div role="alert" className="space-y-3 p-4">
        <p>{errorMessage(pdf.error)}</p>
        <Button onClick={() => void pdf.refetch()}>Повторить загрузку PDF</Button>
      </div>
    );
  if (bid && pdf.isPending)
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
