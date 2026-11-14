import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { downloadBlob } from '@/lib/download';
import { usePdf } from './pdf-queries';

export function PdfDownload({
  bid,
  label = 'Скачать PDF',
  primary = false,
}: {
  bid?: string;
  label?: string;
  primary?: boolean;
}) {
  const pdf = usePdf(bid);
  return (
    <Button
      variant={primary ? 'default' : 'outline'}
      disabled={!pdf.data}
      onClick={() => {
        if (pdf.data) downloadBlob(pdf.data, 'document.pdf');
      }}
    >
      <Download className="size-4" />
      {label}
    </Button>
  );
}
