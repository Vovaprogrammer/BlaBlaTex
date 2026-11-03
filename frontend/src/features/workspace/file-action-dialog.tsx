import { useState } from 'react';
import { Dialog } from 'radix-ui';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/form-field';
import { fileName } from './file-tree-data';
import type { FileAction } from './file-actions';

const titles = {
  'create-file': 'Создать файл',
  'create-folder': 'Создать папку',
  rename: 'Переименовать',
  move: 'Переместить',
  delete: 'Удалить',
};
export function FileActionDialog({
  action,
  pending,
  error,
  onSubmit,
  onClose,
}: {
  action: FileAction;
  pending: boolean;
  error?: string;
  onSubmit: (value: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(
    action.kind === 'rename'
      ? fileName(action.path)
      : action.kind === 'move'
        ? action.path
        : action.path
          ? action.path + '/'
          : '',
  );
  const [validation, setValidation] = useState('');
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 max-h-[90svh] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border bg-card p-6 shadow-xl"
          onEscapeKeyDown={(event) => {
            if (pending) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (pending) event.preventDefault();
          }}
        >
          <Dialog.Title className="text-xl font-semibold">{titles[action.kind]}</Dialog.Title>
          <Dialog.Description className="my-4 break-words text-sm text-muted-foreground">
            {action.kind === 'delete'
              ? `Удалить «${action.path}»${action.folder ? ' со всеми вложенными файлами' : ''}? Это действие нельзя отменить.`
              : action.kind === 'rename' || action.kind === 'move'
                ? `Текущий путь: ${action.path}`
                : 'Укажите путь относительно корня проекта.'}
          </Dialog.Description>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!value.trim() && action.kind !== 'delete') {
                setValidation('Введите имя или путь');
                return;
              }
              if (action.kind === 'rename' && (value.includes('/') || value.includes('\\'))) {
                setValidation('В имени не должно быть разделителей пути');
                return;
              }
              setValidation('');
              onSubmit(value);
            }}
            className="space-y-5"
          >
            {action.kind !== 'delete' && (
              <FormField
                label={action.kind === 'rename' ? 'Новое имя' : 'Путь'}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                disabled={pending}
                error={validation || error}
                autoComplete="off"
              />
            )}
            {action.kind === 'delete' && error && (
              <p role="alert" className="text-destructive">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-3">
              <Button type="button" variant="outline" onClick={onClose} disabled={pending}>
                Отменить
              </Button>
              <Button
                type="submit"
                variant={action.kind === 'delete' ? 'destructive' : 'default'}
                disabled={pending}
              >
                {pending ? 'Подождите…' : titles[action.kind]}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
