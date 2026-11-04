import { lazy, Suspense, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import type { ProjectFile } from '@/features/workspace/file-tree-data';
import { initialPdfPosition } from '@/features/pdf/pdf-position';
import { useProjectBlob } from './material-queries';
import { DownloadFile } from './download-file';
const PdfViewer = lazy(() =>
  import('@/features/pdf/pdf-viewer').then((module) => ({ default: module.PdfViewer })),
);

export function BinaryPreview({ id, file }: { id: string; file: ProjectFile }) {
  const query = useProjectBlob(id, file);
  const [position] = useState(initialPdfPosition);
  if (query.isError)
    return (
      <div role="alert" className="space-y-3 p-4">
        <p>{errorMessage(query.error)}</p>
        <Button onClick={() => void query.refetch()}>Повторить загрузку файла</Button>
      </div>
    );
  if (!query.data)
    return (
      <p role="status" className="p-4">
        Загружаем файл…
      </p>
    );
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
        <p className="min-w-0 break-all text-sm font-semibold">{file.path}</p>
        <DownloadFile id={id} file={file} />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {file.mime === 'application/pdf' ? (
          <Suspense
            fallback={
              <p role="status" className="p-4">
                Открываем PDF…
              </p>
            }
          >
            <PdfViewer blob={query.data} position={position} />
          </Suspense>
        ) : file.mime?.startsWith('image/') ? (
          <ImagePreview blob={query.data} path={file.path} retry={() => void query.refetch()} />
        ) : (
          <p className="p-4 text-sm text-muted-foreground">
            Для этого формата доступно скачивание.
            {file.role === 'material' &&
              ' Текст материала можно открыть кнопкой «Текст для помощника».'}
          </p>
        )}
      </div>
    </div>
  );
}
function ImagePreview({ blob, path, retry }: { blob: Blob; path: string; retry: () => void }) {
  const [url, setUrl] = useState('');
  const [failed, setFailed] = useState('');
  useEffect(() => {
    const value = URL.createObjectURL(blob);
    // URL — внешний ресурс браузера; освобождаем при смене файла или закрытии вкладки.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUrl(value);
    return () => URL.revokeObjectURL(value);
  }, [blob]);
  if (url && failed === url)
    return (
      <div role="alert" className="space-y-3 p-4">
        <p>Не удалось открыть изображение.</p>
        <Button onClick={retry}>Повторить загрузку изображения</Button>
      </div>
    );
  return url ? (
    <div className="flex min-h-full items-start justify-center p-4">
      <img
        src={url}
        alt={path}
        onError={() => setFailed(url)}
        className="max-w-full object-contain"
      />
    </div>
  ) : (
    <p role="status" className="p-4">
      Открываем изображение…
    </p>
  );
}
