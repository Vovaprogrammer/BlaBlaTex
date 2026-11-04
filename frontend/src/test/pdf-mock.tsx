import { useEffect, type ReactNode } from 'react';

// В jsdom нет canvas/Worker. Настоящий PDF.js проверяется отдельно в Chrome.
export function Document({
  file,
  children,
  onLoadSuccess,
}: {
  file: Blob;
  children: ReactNode;
  onLoadSuccess: (data: { numPages: number }) => void;
}) {
  useEffect(() => {
    onLoadSuccess({ numPages: 3 });
    // Модель сообщает о загрузке один раз для каждого файла.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);
  return <div>{children}</div>;
}
export function Page({ pageNumber }: { pageNumber: number }) {
  return <p>Содержимое PDF: страница {pageNumber}</p>;
}
