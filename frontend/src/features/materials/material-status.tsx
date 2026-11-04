import { CheckCircle2, CircleAlert, CircleHelp, Clock3 } from 'lucide-react';
import type { ProjectFile } from '@/features/workspace/file-tree-data';
import { useMaterialText } from './material-queries';

export function MaterialStatus({
  id,
  file,
  compact = false,
}: {
  id: string;
  file: ProjectFile;
  compact?: boolean;
}) {
  const query = useMaterialText(id, file, 0, 1);
  const status = query.data?.status;
  const label =
    status === 'ready'
      ? 'Готово для помощника'
      : status === 'failed'
        ? 'Ошибка обработки'
        : status === 'pending'
          ? 'Обрабатывается'
          : query.isError
            ? 'Статус недоступен'
            : 'Проверяем статус…';
  const Icon =
    status === 'ready'
      ? CheckCircle2
      : status === 'failed'
        ? CircleAlert
        : query.isError
          ? CircleHelp
          : Clock3;
  return (
    <span
      role={compact ? 'img' : 'status'}
      aria-label={compact ? label : undefined}
      title={query.data?.error ?? label}
      className={`inline-flex min-w-0 items-center gap-2 ${status === 'failed' ? 'text-destructive' : 'text-muted-foreground'}`}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      {!compact && <span className="break-words">{label}</span>}
    </span>
  );
}
