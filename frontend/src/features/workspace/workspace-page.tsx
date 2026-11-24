import { lazy, Suspense, useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { FolderOpen, LockKeyhole, MessageSquare } from 'lucide-react';
import type { components } from '@/api/schema';
import { AppHeader } from '@/components/app-header';
import { Button } from '@/components/ui/button';
import { ErrorState, LoadingState } from '@/components/screen-state';
import { WorkspaceLayout, type MobileSection } from './workspace-layout';
import { WorkspaceHints } from './workspace-hints';
import { ProjectChats } from './workspace-placeholders';
import { useChatData } from '@/features/chat/chat-data';
import { useChatActions } from '@/features/chat/use-chat-actions';
import { useOlderMessages } from '@/features/chat/use-older-messages';
import { PlanPanel } from '@/features/plan/plan-panel';
import { useReportPlan } from '@/features/plan/plan-data';
import { ProjectChat } from '@/features/chat/project-chat';
import { useProject, useProjectTree } from './workspace-queries';
import { EditorNavigationContext, type OpenFileAtLine } from '@/features/editor/editor-navigation';
import { useDraftStore, useProjectLock } from '@/features/editor/draft-context';
import { toast } from 'sonner';
import { FileTree } from './file-tree';
import { DocumentTabs } from './document-tabs';
import { initialTabs, tabsReducer } from './workspace-tabs';
import { initialPdfPosition } from '@/features/pdf/pdf-position';
import { useBuild } from '@/features/pdf/use-build';
import { BuildToolbar } from '@/features/pdf/build-toolbar';
import { PdfDownload } from '@/features/pdf/pdf-download';
import { BuildErrors } from '@/features/pdf/build-errors';
import { useProjects } from '@/features/projects/project-queries';
import { ProjectActions } from '@/features/projects/project-actions';
import { useWorkspaceEvents } from '@/features/events/use-workspace-events';
import { EventStatus } from '@/features/events/event-status';
import { useMaterialUpload } from '@/features/materials/use-material-upload';
import { ChecksPanel } from '@/features/checks/checks-panel';
import { WorkDataDialog } from '@/features/projects/work-data-dialog';
const PdfPanel = lazy(() =>
  import('@/features/pdf/pdf-panel').then((module) => ({ default: module.PdfPanel })),
);

export function WorkspacePage() {
  const { id = '' } = useParams();
  return <WorkspaceProject key={id} id={id} />;
}

function WorkspaceProject({ id }: { id: string }) {
  const project = useProject(id);
  const [section, setSection] = useState<MobileSection>('chat');
  const [sidebar, setSidebar] = useState<'files' | 'chats'>('files');
  const [showPlan, setShowPlan] = useState(false);
  const [workData, setWorkData] = useState<{ field: string | null }>();
  const buildPanel = useRef<HTMLDivElement>(null);
  const plan = useReportPlan(id, Boolean(project.data) && showPlan);
  const [tabs, dispatch] = useReducer(tabsReducer, initialTabs);
  const [pdfPosition] = useState(initialPdfPosition);
  const build = useBuild(id);
  const tree = useProjectTree(id);
  const drafts = useDraftStore();
  const lockedRun = useProjectLock(id);
  const upload = useMaterialUpload(id);
  const chat = useChatData(id, Boolean(project.data));
  const chatActions = useChatActions(id, upload, chat.refresh);
  const older = useOlderMessages(id, chat.messages, chat.history.data?.has_more ?? false);
  const events = useWorkspaceEvents(
    id,
    Boolean(project.data),
    (change, preserve) => {
      dispatch({ kind: 'change', change, preserve });
    },
    chat,
  );
  const [params, setParams] = useSearchParams();
  const showChat = useCallback(() => {
    setShowPlan(false);
    setSection('chat');
  }, []);
  const openPlan = useCallback(() => {
    setShowPlan(true);
    setSection('chat');
  }, []);
  const openFileAtLine = useCallback<OpenFileAtLine>((path, line) => {
    dispatch({ kind: 'open', path, line });
    setSection('document');
  }, []);
  useEffect(() => {
    const path = params.get('file');
    if (!path || !tree.data) return;
    const line = Number(params.get('line'));
    if (
      tree.data.items.some((file) => file.path === path && file.kind !== 'folder') ||
      drafts.get(id, path)
    ) {
      // Синхронизация с внешним переходом по URL после асинхронной загрузки дерева.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      openFileAtLine(path, Number.isSafeInteger(line) && line > 0 ? line : undefined);
    } else toast.error('Файл не найден в проекте');
    const next = new URLSearchParams(params);
    next.delete('file');
    next.delete('line');
    setParams(next, { replace: true });
  }, [params, setParams, tree.data, drafts, id, openFileAtLine]);
  return (
    <EditorNavigationContext.Provider value={openFileAtLine}>
      <div className="flex h-svh min-h-[400px] flex-col overflow-hidden">
        <h1 className="sr-only">Рабочее окно</h1>
        <AppHeader actions={<PdfDownload bid={build.shownPdf?.id} label="Экспорт PDF" primary />}>
          <div className="flex min-w-0 items-center gap-2">
            <ProjectPicker id={id} project={project.data} />
            {project.data && <ProjectActions project={project.data} />}
          </div>
        </AppHeader>
        {workData && project.data && (
          <WorkDataDialog
            project={project.data}
            locked={Boolean(lockedRun)}
            initialField={workData.field}
            onClose={() => setWorkData(undefined)}
            returnFocus={() => buildPanel.current?.focus()}
          />
        )}
        {project.data && <WorkspaceHints />}
        {project.data && project.isError && (
          <ErrorState
            className="mx-3 mt-3 shrink-0 sm:mx-6"
            error={project.error}
            retry={() => void project.refetch()}
            retrying={project.isFetching}
          />
        )}
        {project.data && lockedRun && (
          <section
            aria-label="Блокировка файлов"
            className="mx-3 mt-3 flex shrink-0 flex-wrap items-center gap-2 rounded-xl border border-ring/40 bg-secondary px-3 py-2 sm:mx-6 sm:gap-3"
          >
            <LockKeyhole aria-hidden="true" className="size-5 shrink-0 text-ring" />
            <p role="status" className="min-w-0 flex-1 text-sm">
              Агент работает с проектом. Файлы доступны только для чтения.
            </p>
            <Button
              size="sm"
              variant="outline"
              disabled={chatActions.cancel.isPending || chatActions.stopping === lockedRun}
              onClick={() => chatActions.cancel.mutate(lockedRun)}
            >
              {chatActions.cancel.isPending || chatActions.stopping === lockedRun
                ? 'Останавливаем…'
                : 'Остановить'}
            </Button>
          </section>
        )}
        {project.data ? (
          <WorkspaceLayout
            section={section}
            onSectionChange={setSection}
            files={
              <section
                aria-label="Файлы и чаты проекта"
                className="@container/sidebar flex h-full min-h-0 flex-col"
              >
                <div className="grid grid-cols-2 gap-1 p-2 @[210px]/sidebar:p-3">
                  {(
                    [
                      ['files', 'Файлы', FolderOpen],
                      ['chats', 'Чаты', MessageSquare],
                    ] as const
                  ).map(([value, label, Icon]) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={sidebar === value}
                      onClick={() => setSidebar(value)}
                      className={`flex min-h-10 min-w-0 items-center justify-center gap-2 rounded-xl border px-1 text-sm focus-visible:outline-2 focus-visible:outline-ring ${sidebar === value ? 'border-ring bg-primary text-primary-foreground' : 'border-transparent'}`}
                    >
                      <Icon
                        className="hidden size-4 shrink-0 @[210px]/sidebar:block"
                        aria-hidden="true"
                      />
                      <span className="min-w-0 truncate">{label}</span>
                    </button>
                  ))}
                </div>
                <h2
                  className="truncate border-b px-4 pb-4 font-semibold"
                  title={project.data.title}
                >
                  {project.data.title}
                </h2>
                {sidebar === 'chats' ? (
                  <ProjectChats onOpen={showChat} />
                ) : (
                  <FileTree
                    id={id}
                    upload={upload}
                    onOpen={(file) => {
                      openFileAtLine(file.path);
                    }}
                    onChange={(change) => {
                      dispatch({ kind: 'change', change });
                      if (change.kind === 'create' && !change.folder) setSection('document');
                    }}
                  />
                )}
              </section>
            }
            chat={
              <div className="flex h-full min-h-0 flex-col">
                <div
                  role="group"
                  aria-label="Вкладки чата"
                  className="flex shrink-0 gap-2 border-b p-2"
                >
                  <Button
                    size="sm"
                    variant={showPlan ? 'ghost' : 'secondary'}
                    aria-pressed={!showPlan}
                    onClick={showChat}
                  >
                    Чат
                  </Button>
                  <Button
                    size="sm"
                    variant={showPlan ? 'secondary' : 'ghost'}
                    aria-pressed={showPlan}
                    onClick={openPlan}
                  >
                    План отчёта
                  </Button>
                </div>
                <div hidden={showPlan} className="min-h-0 flex-1">
                  <ProjectChat
                    project={id}
                    chat={chat}
                    actions={chatActions}
                    older={older}
                    onOpenPlan={openPlan}
                  />
                </div>
                <div className={showPlan ? 'flex min-h-0 flex-1' : 'hidden'} hidden={!showPlan}>
                  <PlanPanel
                    id={id}
                    query={plan}
                    active={chat.history.data?.active_run ?? null}
                    locked={Boolean(lockedRun) || !chat.history.data}
                    actions={chatActions}
                    onConfirmed={showChat}
                  />
                </div>
              </div>
            }
            document={
              <DocumentTabs
                id={id}
                state={tabs}
                dispatch={dispatch}
                tools={
                  <>
                    <EventStatus {...events} />
                    <div ref={buildPanel} tabIndex={-1} role="region" aria-label="Сборка отчёта">
                      <BuildToolbar id={id} controller={build} previewOpen={tabs.active === null}>
                        <ChecksPanel
                          id={id}
                          openFields={(field) => setWorkData({ field })}
                          openBuild={() => {
                            dispatch({ kind: 'select', path: null });
                            setSection('document');
                            requestAnimationFrame(() => {
                              buildPanel.current?.scrollIntoView?.({ block: 'nearest' });
                              buildPanel.current?.focus();
                            });
                          }}
                        />
                      </BuildToolbar>
                    </div>
                    {build.active &&
                      !build.busy &&
                      (build.active.errors.length > 0 ||
                        ['error', 'timeout'].includes(build.active.status) ||
                        build.active.warnings_count > 0) && (
                        <BuildErrors key={build.active.id} id={id} build={build.active} />
                      )}
                  </>
                }
                pdf={
                  <section aria-label="Предпросмотр PDF" className="h-full min-h-0">
                    <Suspense
                      fallback={<LoadingState className="p-4">Открываем просмотрщик…</LoadingState>}
                    >
                      <PdfPanel bid={build.shownPdf?.id} position={pdfPosition} />
                    </Suspense>
                  </section>
                }
              />
            }
          />
        ) : (
          <main className="space-y-5 p-8">
            {project.isPending ? (
              <LoadingState>Открываем проект…</LoadingState>
            ) : (
              <ErrorState
                error={project.error}
                retry={() => void project.refetch()}
                retrying={project.isFetching}
                retryLabel="Повторить"
              />
            )}
            <Link to="/projects" className="text-ring underline">
              К списку проектов
            </Link>
          </main>
        )}
      </div>
    </EditorNavigationContext.Provider>
  );
}

function ProjectPicker({
  id,
  project,
}: {
  id: string;
  project?: components['schemas']['ProjectOut'];
}) {
  const navigate = useNavigate();
  const projects = useProjects();
  const items = projects.data?.items ?? [];
  return (
    <label className="flex min-w-0 max-w-md items-center gap-2 sm:border-l sm:pl-7">
      <FolderOpen className="hidden size-6 shrink-0 text-ring sm:block" aria-hidden="true" />
      <span className="sr-only">Выбрать проект</span>
      <select
        value={id}
        onChange={(event) => navigate(`/projects/${encodeURIComponent(event.target.value)}`)}
        className="min-h-11 w-full min-w-0 truncate rounded-lg bg-card pr-2 text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring"
        title={project?.title}
      >
        {!items.some((item) => item.id === id) && (
          <option value={id}>{project?.title ?? 'Проект'}</option>
        )}
        {items.map((item) => (
          <option key={item.id} value={item.id}>
            {item.title}
          </option>
        ))}
      </select>
    </label>
  );
}
