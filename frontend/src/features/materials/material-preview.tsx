import { lazy, Suspense, useState } from 'react';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import type { ProjectFile } from '@/features/workspace/file-tree-data';
import type { EditorTarget } from '@/features/editor/editor-navigation';
import { FileEditor } from '@/features/editor/file-editor';
import { useMaterialText } from './material-queries';
import { MaterialStatus } from './material-status';
import { DownloadFile } from './download-file';
const BinaryPreview = lazy(() =>
  import('./binary-preview').then((module) => ({ default: module.BinaryPreview })),
);

export function MaterialPreview({
  id,
  file,
  target,
}: {
  id: string;
  file: ProjectFile;
  target?: EditorTarget;
}) {
  const [view, setView] = useState<'file' | 'text'>('file');
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b p-3 text-xs">
        <MaterialStatus id={id} file={file} />
        <div className="flex flex-wrap gap-1" aria-label="Вид материала">
          <Button
            variant={view === 'file' ? 'secondary' : 'ghost'}
            size="sm"
            aria-pressed={view === 'file'}
            onClick={() => setView('file')}
          >
            Файл
          </Button>
          <Button
            variant={view === 'text' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-auto min-h-8 whitespace-normal"
            aria-pressed={view === 'text'}
            onClick={() => setView('text')}
          >
            Текст для помощника
          </Button>
        </div>
        {file.kind === 'text' && <DownloadFile id={id} file={file} />}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {view === 'text' ? (
          <ExtractedText key={file.version} id={id} file={file} />
        ) : file.kind === 'text' ? (
          <FileEditor id={id} path={file.path} version={file.version} target={target} />
        ) : (
          <Suspense
            fallback={
              <p role="status" className="p-4">
                Открываем материал…
              </p>
            }
          >
            <BinaryPreview key={file.version} id={id} file={file} />
          </Suspense>
        )}
      </div>
    </div>
  );
}
function ExtractedText({ id, file }: { id: string; file: ProjectFile }) {
  const [offset, setOffset] = useState(0);
  const limit = 20_000;
  const query = useMaterialText(id, file, offset, limit);
  if (query.isError)
    return (
      <div role="alert" className="space-y-3 p-4">
        <p>{errorMessage(query.error)}</p>
        <Button onClick={() => void query.refetch()}>Повторить получение текста</Button>
      </div>
    );
  if (!query.data)
    return (
      <p role="status" className="p-4">
        Читаем текст материала…
      </p>
    );
  const data = query.data;
  return (
    <div className="h-full space-y-4 overflow-auto p-4 text-sm">
      <p className="font-semibold">Что видит помощник в этом материале</p>
      {data.status === 'pending' ? (
        <p role="status">Материал обрабатывается. Текст появится автоматически.</p>
      ) : data.status === 'failed' ? (
        <p role="alert">
          {data.error ??
            'Не удалось обработать материал. Исходный файл доступен для просмотра и скачивания.'}
        </p>
      ) : (
        <>
          {data.description && (
            <p className="whitespace-pre-wrap break-words">{data.description}</p>
          )}
          <pre className="whitespace-pre-wrap break-words font-mono text-xs">
            {data.text || 'Текст в материале не найден.'}
          </pre>
          {data.total > limit && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
              >
                Назад
              </Button>
              <span>
                Символы {offset + 1}–{Math.min(offset + limit, data.total)} из {data.total}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={offset + limit >= data.total}
                onClick={() => setOffset(offset + limit)}
              >
                Далее
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
