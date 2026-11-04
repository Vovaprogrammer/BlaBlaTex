import { useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import { materialAccept, type MaterialUpload } from './use-material-upload';

export function UploadMaterials({ upload, dir }: { upload: MaterialUpload; dir: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const send = (files: File[]) => {
    if (files.length && !upload.isPending) upload.mutate({ files, dir });
  };
  return (
    <section
      aria-label="Загрузка материалов"
      className={`shrink-0 space-y-2 rounded-xl border border-dashed p-2 text-xs ${dragging ? 'border-ring bg-accent' : 'border-border'}`}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes('Files')) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event) => {
        if (event.dataTransfer.types.includes('Files')) {
          event.preventDefault();
          event.stopPropagation();
          setDragging(false);
          send(Array.from(event.dataTransfer.files));
        }
      }}
    >
      <input
        ref={input}
        type="file"
        multiple
        accept={materialAccept}
        className="sr-only"
        aria-label="Выбрать материалы"
        disabled={upload.isPending}
        onChange={(event) => {
          send(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
      <Button
        variant="outline"
        className="h-auto min-h-10 w-full whitespace-normal px-2 py-2 text-xs"
        disabled={upload.isPending}
        onClick={() => input.current?.click()}
      >
        <Upload className="size-4 shrink-0" aria-hidden="true" />
        Загрузить материалы
      </Button>
      <p className="break-words text-muted-foreground">Перетащите файлы сюда. До 20 МБ каждый.</p>
      <p className="break-all text-muted-foreground">
        В папку: {dir.replace(/^materials/, 'Материалы')}
      </p>
      <p className="text-muted-foreground">Файлы с совпадающими именами заменяются.</p>
      {upload.isPending && (
        <div className="space-y-1">
          <p role="status">
            {upload.progress.checking ? 'Файлы переданы. Проверяем…' : 'Загружаем материалы…'}
          </p>
          <progress
            aria-label="Передача материалов"
            max={100}
            value={upload.progress.percent ?? undefined}
            className="h-2 w-full accent-primary"
          />
        </div>
      )}
      {upload.isSuccess && <p role="status">Загружено файлов: {upload.data.items.length}</p>}
      {upload.isError &&
        !(upload.error instanceof DOMException && upload.error.name === 'AbortError') && (
          <p role="alert" className="break-words text-destructive">
            {errorMessage(upload.error)}
          </p>
        )}
    </section>
  );
}
