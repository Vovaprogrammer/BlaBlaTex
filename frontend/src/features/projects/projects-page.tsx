import { lazy, Suspense, useState } from 'react';
import { Link } from 'react-router';
import { Clock, FileText, FolderOpen, Grid2X2, List, Plus, Search } from 'lucide-react';
import type { components } from '@/api/schema';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import { useProjects } from './project-queries';
import { ProjectActions } from './project-actions';
const CreateProject = lazy(() =>
  import('./create-project').then((module) => ({ default: module.CreateProject })),
);

const projectKinds = {
  lab: 'Лабораторная работа',
  vkr: 'Выпускная работа',
  article: 'Статья',
  slides: 'Презентация',
};
function edited(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Дата не указана'
    : new Intl.DateTimeFormat('ru', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function ProjectsPage() {
  const query = useProjects();
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState('all');
  const [sort, setSort] = useState('updated');
  const [list, setList] = useState(false);
  const [creating, setCreating] = useState(false);
  const projects = query.data?.items ?? [];
  const visible = projects
    .filter(
      (project) =>
        (kind === 'all' || project.kind === kind) &&
        project.title.toLocaleLowerCase('ru').includes(search.trim().toLocaleLowerCase('ru')),
    )
    .sort((a, b) =>
      sort === 'title'
        ? a.title.localeCompare(b.title, 'ru')
        : b.updated_at.localeCompare(a.updated_at),
    );
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-6">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold sm:text-4xl">Ваши проекты</h1>
          <p className="mt-2 text-muted-foreground">
            Создавайте документы по шаблонам и продолжайте работу.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="size-5" />
          Новый проект
        </Button>
      </header>
      {creating && (
        <Suspense fallback={<p role="status">Открываем форму…</p>}>
          <CreateProject onClose={() => setCreating(false)} />
        </Suspense>
      )}
      {query.isPending ? (
        <p role="status">Загружаем проекты…</p>
      ) : query.isError && !query.data ? (
        <div role="alert" className="space-y-3">
          <p>{errorMessage(query.error)}</p>
          <Button onClick={() => void query.refetch()}>Повторить загрузку проектов</Button>
        </div>
      ) : (
        <>
          {query.isError && (
            <p role="alert" className="text-destructive">
              {errorMessage(query.error)} Показан ранее загруженный список.
            </p>
          )}
          {projects.length ? (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <label className="relative w-full min-w-0 flex-none sm:min-w-48 sm:flex-1">
                  <span className="sr-only">Поиск проектов</span>
                  <Search
                    aria-hidden="true"
                    className="absolute left-3 top-3 size-5 text-muted-foreground"
                  />
                  <input
                    type="search"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Поиск проектов…"
                    className="min-h-11 w-full min-w-0 rounded-xl border bg-secondary py-2 pl-10 pr-3 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </label>
                <label className="min-w-0">
                  <span className="sr-only">Тип проекта</span>
                  <select
                    value={kind}
                    onChange={(event) => setKind(event.target.value)}
                    className="min-h-11 max-w-full rounded-xl border bg-secondary px-3"
                  >
                    <option value="all">Все проекты ({projects.length})</option>
                    {Object.entries(projectKinds).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="min-w-0">
                  <span className="sr-only">Сортировка проектов</span>
                  <select
                    value={sort}
                    onChange={(event) => setSort(event.target.value)}
                    className="min-h-11 max-w-full rounded-xl border bg-secondary px-3"
                  >
                    <option value="updated">Сначала изменённые</option>
                    <option value="title">По названию</option>
                  </select>
                </label>
                <div className="flex rounded-xl border p-1" aria-label="Вид списка проектов">
                  <Button
                    size="icon"
                    variant={list ? 'ghost' : 'default'}
                    aria-label="Карточки проектов"
                    aria-pressed={!list}
                    onClick={() => setList(false)}
                  >
                    <Grid2X2 />
                  </Button>
                  <Button
                    size="icon"
                    variant={list ? 'default' : 'ghost'}
                    aria-label="Список проектов"
                    aria-pressed={list}
                    onClick={() => setList(true)}
                  >
                    <List />
                  </Button>
                </div>
              </div>
              {visible.length ? (
                <div className={list ? 'space-y-3' : 'grid gap-5 md:grid-cols-2 xl:grid-cols-3'}>
                  {visible.map((project) => (
                    <ProjectCard key={project.id} project={project} />
                  ))}
                </div>
              ) : (
                <div className="space-y-3 rounded-xl border border-dashed p-8 text-center">
                  <h2 className="text-xl font-semibold">Проекты не найдены</h2>
                  <p className="text-muted-foreground">Измените запрос или тип проекта.</p>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setSearch('');
                      setKind('all');
                    }}
                  >
                    Сбросить фильтры
                  </Button>
                </div>
              )}
            </>
          ) : (
            <div className="flex min-h-72 flex-col items-center justify-center gap-4 rounded-2xl border border-dashed p-6 text-center">
              <FolderOpen className="size-12 text-ring" aria-hidden="true" />
              <h2 className="text-2xl font-semibold">Пока нет проектов</h2>
              <p className="max-w-md text-muted-foreground">
                Создайте первый проект по шаблону, чтобы начать работу над документом.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: components['schemas']['ProjectOut'] }) {
  return (
    <article className="relative min-w-0 rounded-2xl border bg-secondary transition-colors hover:border-ring">
      <div className="absolute right-2 top-2">
        <ProjectActions project={project} />
      </div>
      <Link
        to={`/projects/${encodeURIComponent(project.id)}`}
        className="block space-y-4 rounded-2xl p-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 pr-8">
          <span className="rounded-xl bg-primary/25 p-3 text-ring">
            <FileText aria-hidden="true" className="size-6" />
          </span>
          <span className="rounded-lg border px-2 py-1 text-xs text-muted-foreground">
            {projectKinds[project.kind]}
          </span>
        </div>
        <h2 className="break-words text-xl font-semibold">{project.title}</h2>
        <p className="flex items-start gap-2 border-t pt-3 text-sm text-muted-foreground">
          <Clock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>
            Изменён <time dateTime={project.updated_at}>{edited(project.updated_at)}</time>
          </span>
        </p>
      </Link>
    </article>
  );
}
