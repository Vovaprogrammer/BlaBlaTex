import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { components } from '@/api/schema';
import { useOpenFileAtLine } from '@/features/editor/editor-navigation';
import { useProjectTree } from '@/features/workspace/workspace-queries';
import { errorMessage } from '@/app/query-client';
import { Button } from '@/components/ui/button';

export function BuildErrors({
  id,
  build,
}: {
  id: string;
  build: components['schemas']['BuildOut'];
}) {
  const tree = useProjectTree(id);
  const open = useOpenFileAtLine();
  const [showLog, setShowLog] = useState(false);
  const log = useQuery({
    queryKey: ['builds', build.id, 'log'],
    enabled: showLog,
    queryFn: async ({ signal }) =>
      (
        await api.GET('/api/v1/builds/{bid}/log', {
          params: { path: { bid: build.id } },
          parseAs: 'text',
          signal,
        })
      ).data ?? '',
  });
  const errors = build.errors.filter((issue) => issue.severity === 'error').length;
  return (
    <details open={build.status !== 'ok'} className="border-b text-sm">
      <summary className="cursor-pointer px-3 py-2 font-semibold focus-visible:outline-2 focus-visible:outline-ring">
        Ошибки и предупреждения: {build.errors.length}
      </summary>
      <div className="max-h-56 space-y-3 overflow-auto px-3 pb-3">
        {!build.errors.length && (
          <p className="text-muted-foreground">
            {build.status === 'timeout'
              ? 'Сборка заняла слишком много времени. Попробуйте ещё раз.'
              : 'Подробностей нет. Посмотрите журнал сборки.'}
          </p>
        )}
        {build.errors.map((issue, index) => {
          const path = issue.file?.replace(/^(\.\/)+/, '');
          const file = tree.data?.items.find((item) => item.path === path && item.kind === 'text');
          return (
            <div key={index} className="space-y-1 rounded-lg border bg-secondary p-3">
              <p
                className={
                  issue.severity === 'error' ? 'text-destructive' : 'text-muted-foreground'
                }
              >
                {issue.severity === 'error' ? 'Ошибка' : 'Предупреждение'}: {issue.message}
              </p>
              {file ? (
                <button
                  type="button"
                  className="max-w-full break-all text-left text-ring underline focus-visible:outline-2 focus-visible:outline-ring"
                  onClick={() => open(file.path, issue.line ?? undefined)}
                >
                  {file.path}
                  {issue.line ? `:${issue.line}` : ''}
                </button>
              ) : (
                issue.file && (
                  <p className="break-all text-muted-foreground">
                    {issue.file}
                    {issue.line ? `:${issue.line}` : ''} — файл недоступен в проекте
                  </p>
                )
              )}
              {issue.context && (
                <pre className="overflow-auto whitespace-pre-wrap break-words font-mono text-xs">
                  {issue.context}
                </pre>
              )}
            </div>
          );
        })}
        {errors === 0 && build.warnings_count > build.errors.length && (
          <p className="text-muted-foreground">Дополнительные предупреждения доступны в журнале.</p>
        )}
        <Button size="sm" variant="outline" onClick={() => setShowLog((value) => !value)}>
          {showLog ? 'Скрыть журнал сборки' : 'Показать журнал сборки'}
        </Button>
        {showLog &&
          (log.isPending ? (
            <p role="status">Загружаем журнал…</p>
          ) : log.isError ? (
            <div role="alert">
              <p>{errorMessage(log.error)}</p>
              <Button onClick={() => void log.refetch()}>Повторить загрузку журнала</Button>
            </div>
          ) : (
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border p-3 text-xs">
              {log.data || 'Журнал пуст'}
            </pre>
          ))}
      </div>
    </details>
  );
}
