import { useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Dialog } from 'radix-ui';
import { ClipboardCheck } from 'lucide-react';
import type { components } from '@/api/schema';
import { Button } from '@/components/ui/button';
import { ErrorState, LoadingState } from '@/components/screen-state';
import { useOpenFileAtLine } from '@/features/editor/editor-navigation';
import { useProjectTree } from '@/features/workspace/workspace-queries';
import { useChecks } from './checks-query';

type Finding = components['schemas']['CheckFinding'];

export function ChecksPanel({
  id,
  openFields,
  openBuild,
}: {
  id: string;
  openFields: (field: string | null) => void;
  openBuild: () => void;
}) {
  const [open, setOpen] = useState(false);
  const leaving = useRef(false);
  const query = useChecks(id, open);
  const tree = useProjectTree(id);
  const openFile = useOpenFileAtLine();
  const navigate = useNavigate();
  const findings = [...(query.data?.findings ?? [])].sort(
    (a, b) => Number(a.level === 'warning') - Number(b.level === 'warning'),
  );
  function visit(finding: Finding) {
    leaving.current = true;
    setOpen(false);
    if (finding.place === 'profile') navigate('/profile');
    else if (finding.place === 'fields') openFields(finding.field);
    else if (finding.place === 'build') openBuild();
    else if (finding.file) openFile(finding.file, finding.line ?? undefined);
  }
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button
          variant="outline"
          onClick={() => {
            leaving.current = false;
          }}
        >
          <ClipboardCheck aria-hidden="true" />
          Проверить отчёт
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[85svh] w-[calc(100%-2rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-hidden rounded-2xl border bg-card p-5 shadow-xl"
          onCloseAutoFocus={(event) => {
            if (leaving.current) event.preventDefault();
          }}
        >
          <Dialog.Title className="text-xl font-semibold">Проверка отчёта</Dialog.Title>
          <Dialog.Description className="text-sm text-muted-foreground">
            Замечания относятся к сохранённым файлам на момент проверки. Нажмите на замечание, чтобы
            перейти к исправлению.
          </Dialog.Description>
          <div className="min-h-0 space-y-4 overflow-y-auto">
            {import.meta.env.VITE_USE_MOCKS === '1' && (
              <p className="text-sm text-muted-foreground">
                Тестовый режим — демонстрационные результаты проверки.
              </p>
            )}
            {query.isFetching && <LoadingState>Проверяем отчёт…</LoadingState>}
            {query.isError && (
              <ErrorState
                error={query.error}
                retry={() => void query.refetch()}
                retrying={query.isFetching}
                retryLabel="Повторить проверку"
              />
            )}
            {query.data && (
              <>
                <p className="text-sm">
                  Ошибок — {query.data.errors_count}, предупреждений — {query.data.warnings_count}.
                </p>
                {!query.data.pdf_checked && (
                  <p role="status" className="text-sm text-muted-foreground">
                    PDF ещё собирается, проверки по нему будут позже
                  </p>
                )}
                {!findings.length && (
                  <p>
                    {query.data.pdf_checked
                      ? 'Замечаний не найдено.'
                      : 'В исходниках замечаний не найдено.'}
                  </p>
                )}
                <ul aria-label="Замечания к отчёту" className="space-y-2">
                  {findings.map((finding, index) => {
                    const available =
                      finding.place !== 'file' ||
                      tree.data?.items.some(
                        (file) => file.path === finding.file && file.kind !== 'folder',
                      );
                    return (
                      <li key={index} className="rounded-lg border p-3">
                        <p
                          className={
                            finding.level === 'error'
                              ? 'text-sm text-destructive'
                              : 'text-sm text-muted-foreground'
                          }
                        >
                          {finding.level === 'error' ? 'Ошибка' : 'Предупреждение'}
                        </p>
                        <button
                          type="button"
                          disabled={!available}
                          onClick={() => visit(finding)}
                          className="w-full break-words text-left text-sm underline decoration-ring underline-offset-4 focus-visible:outline-2 focus-visible:outline-ring disabled:no-underline"
                        >
                          {finding.message}
                        </button>
                        {finding.file && (
                          <p className="break-all text-xs text-muted-foreground">
                            {finding.file}
                            {finding.line ? `:${finding.line}` : ''}
                          </p>
                        )}
                        {!available && (
                          <p className="text-xs text-muted-foreground">
                            Файл недоступен в проекте.
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            {query.data && !query.isError && (
              <Button
                variant="outline"
                disabled={query.isFetching}
                onClick={() => void query.refetch()}
              >
                Проверить ещё раз
              </Button>
            )}
            <Dialog.Close asChild>
              <Button variant="outline">Закрыть</Button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
