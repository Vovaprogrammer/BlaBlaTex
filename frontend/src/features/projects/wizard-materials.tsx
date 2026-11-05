import { useRef } from 'react';
import { Paperclip, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { materialAccept } from '@/features/materials/use-material-upload';

export function WizardMaterials({
  files,
  onFiles,
  disabled,
}: {
  files: File[];
  onFiles: (files: File[]) => void;
  disabled: boolean;
}) {
  const picker = useRef<HTMLInputElement>(null);
  function add(incoming: File[]) {
    if (disabled) return;
    const next = new Map(files.map((file) => [file.name.normalize('NFC'), file]));
    for (const file of incoming) next.set(file.name.normalize('NFC'), file);
    onFiles([...next.values()]);
  }

  return (
    <section aria-label="Материалы для отчёта" className="space-y-3">
      <div
        className="space-y-3 rounded-xl border border-dashed bg-secondary p-4"
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes('Files')) event.preventDefault();
        }}
        onDrop={(event) => {
          if (!event.dataTransfer.types.includes('Files')) return;
          event.preventDefault();
          add(Array.from(event.dataTransfer.files));
        }}
      >
        <p className="text-sm text-muted-foreground">
          Добавьте методичку, данные, код или скриншоты. До 20 МБ на файл. Этот шаг можно
          пропустить.
        </p>
        <input
          type="file"
          multiple
          hidden
          ref={picker}
          accept={materialAccept}
          onChange={(event) => {
            add(Array.from(event.currentTarget.files ?? []));
            event.currentTarget.value = '';
          }}
        />
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => picker.current?.click()}
        >
          <Paperclip aria-hidden="true" /> Выбрать файлы
        </Button>
      </div>
      {files.length > 0 && (
        <ul aria-label="Выбранные файлы" className="max-h-44 space-y-2 overflow-auto">
          {files.map((file) => (
            <li
              key={file.name}
              className="flex min-w-0 items-center justify-between gap-2 rounded-lg border px-3 py-1"
            >
              <span className="min-w-0 break-all text-sm">{file.name}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={disabled}
                aria-label={`Убрать ${file.name}`}
                onClick={() => onFiles(files.filter((item) => item !== file))}
              >
                <X aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
