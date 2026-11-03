import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { FolderOpen, MessageSquare } from 'lucide-react';
import { api } from '@/api/client';
import type { components } from '@/api/schema';
import { AppHeader } from '@/components/app-header';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import { WorkspaceLayout, type MobileSection } from './workspace-layout';
import { ChatPlaceholder, PdfPlaceholder, ProjectChats } from './workspace-placeholders';
import { useProject } from './workspace-queries';

export function WorkspacePage() {
  const { id = '' } = useParams();
  return <WorkspaceProject key={id} id={id} />;
}

function WorkspaceProject({ id }: { id: string }) {
  const project = useProject(id);
  const [section, setSection] = useState<MobileSection>('chat');
  const [sidebar, setSidebar] = useState<'files' | 'chats'>('files');
  return (
    <div className="flex h-svh min-h-[400px] flex-col overflow-hidden">
      <h1 className="sr-only">Рабочее окно</h1>
      <AppHeader>
        <ProjectPicker id={id} project={project.data} />
      </AppHeader>
      {project.data ? (
        <WorkspaceLayout
          section={section}
          onSectionChange={setSection}
          files={
            <section aria-label="Файлы и чаты проекта" className="flex h-full min-h-0 flex-col">
              <div className="grid grid-cols-2 gap-1 p-3">
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
                    className={`flex min-h-10 min-w-0 items-center justify-center gap-2 rounded-xl border text-sm focus-visible:outline-2 focus-visible:outline-ring ${sidebar === value ? 'border-ring bg-primary text-primary-foreground' : 'border-transparent'}`}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden="true" />
                    {label}
                  </button>
                ))}
              </div>
              <h2 className="truncate border-b px-4 pb-4 font-semibold" title={project.data.title}>
                {project.data.title}
              </h2>
              {sidebar === 'chats' ? (
                <ProjectChats onOpen={() => setSection('chat')} />
              ) : (
                <p className="p-4 text-sm text-muted-foreground">Дерево файлов появится здесь.</p>
              )}
            </section>
          }
          chat={<ChatPlaceholder />}
          document={<PdfPlaceholder />}
        />
      ) : (
        <main className="space-y-5 p-8">
          {project.isPending ? (
            <p role="status">Открываем проект…</p>
          ) : (
            <div role="alert" className="space-y-4">
              <p>{errorMessage(project.error)}</p>
              <Button onClick={() => void project.refetch()}>Повторить</Button>
            </div>
          )}
          <Link to="/projects" className="text-ring underline">
            К списку проектов
          </Link>
        </main>
      )}
    </div>
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
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: async ({ signal }) => (await api.GET('/api/v1/projects', { signal })).data,
  });
  const items = projects.data?.items ?? [];
  return (
    <label className="flex min-w-0 max-w-md items-center gap-2 border-l pl-4 sm:pl-7">
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
