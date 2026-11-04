import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
        if (!pdf.data) return;
        const url = URL.createObjectURL(pdf.data);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = 'document.pdf';
        anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 30_000);
      }}
    >
      <Download className="size-4" />
      {label}
    </Button>
  );
}
