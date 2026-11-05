import { useState, useId, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Dialog } from 'radix-ui';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { api } from '@/api/client';
import { ApiError, isRecord } from '@/api/api-error';
import type { components } from '@/api/schema';
import { errorMessage } from '@/app/query-client';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/form-field';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { projectsKey, useProjects } from './project-queries';
import { createProjectSchema, projectFields, type ProjectForm } from './project-form';
import { projectNameHint, templateFieldHint } from './project-field-hints';
import { WizardMaterials } from './wizard-materials';
import { useMaterialUpload } from '@/features/materials/use-material-upload';
import { chatKey, getMessages, postChatMessage } from '@/features/chat/chat-data';

const steps = ['Тип работы', 'Шаблон', 'Данные', 'Материалы'] as const;
const firstMessage = 'Сделай отчёт по загруженным материалам';

export function CreateProject({ onClose }: { onClose: () => void }) {
  const [slug, setSlug] = useState('');
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [pending, setPending] = useState(false);
  const [title, setTitle] = useState('');
  const projects = useProjects();
  const templates = useQuery({
    queryKey: ['templates'],
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/templates', { signal });
      if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать шаблоны.');
      return data;
    },
  });
  const available = templates.data?.items.filter((template) => template.kind === 'lab') ?? [];
  const selected =
    available.find((template) => template.slug === slug)?.slug ?? available[0]?.slug ?? '';
  const detail = useQuery({
    queryKey: ['templates', selected],
    refetchOnWindowFocus: false,
    enabled: Boolean(selected),
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/templates/{slug}', {
        params: { path: { slug: selected } },
        signal,
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать поля шаблона.');
      return data;
    },
  });
  const discipline = detail.data?.discipline;
  const related = new Set(
    available.filter((item) => item.discipline === discipline).map((item) => item.slug),
  );
  const previous = discipline
    ? projects.data?.items
        .filter((item) => related.has(item.template_slug))
        .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0]
    : undefined;
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
          className="fixed left-1/2 top-1/2 z-50 max-h-[90svh] w-[calc(100%-2rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border bg-card p-6 shadow-xl"
          onEscapeKeyDown={(event) => {
            if (pending) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (pending) event.preventDefault();
          }}
        >
          <Dialog.Title className="text-2xl font-semibold">Новый проект</Dialog.Title>
          <ol
            aria-label="Шаги создания проекта"
            className="my-4 grid grid-cols-2 gap-2 sm:grid-cols-4"
          >
            {steps.map((label, index) => (
              <li
                key={label}
                aria-current={index === step ? 'step' : undefined}
                className={`rounded-lg border px-2 py-2 text-xs ${index === step ? 'border-ring bg-primary/25 font-semibold' : 'text-muted-foreground'}`}
              >
                {index + 1}. {label}
              </li>
            ))}
          </ol>
          <Dialog.Description className="mb-4 text-sm text-muted-foreground">
            {step === 0
              ? 'Выберите тип документа, который хотите подготовить.'
              : step === 1
                ? 'Выберите шаблон для своей дисциплины.'
                : step === 2
                  ? 'Заполните данные работы. Данные об обучении берутся из профиля.'
                  : 'Добавьте материалы, на которые будет опираться помощник.'}
          </Dialog.Description>
          {step === 0 && (
            <div className="space-y-3">
              <fieldset className="grid gap-2 sm:grid-cols-2">
                <legend className="sr-only">Тип работы</legend>
                {['Лабораторная', 'ВКР', 'Статья', 'Презентация'].map((kind, index) => (
                  <label
                    key={kind}
                    className={`flex items-center gap-2 rounded-xl border p-3 ${index === 0 ? 'border-ring bg-primary/20' : 'text-muted-foreground'}`}
                  >
                    <input
                      type="radio"
                      name="wizard-kind"
                      defaultChecked={index === 0}
                      disabled={index !== 0}
                    />
                    {kind} {index !== 0 && <span className="ml-auto text-xs">Скоро</span>}
                  </label>
                ))}
              </fieldset>
              <WizardButtons onBack={onClose} backLabel="Отмена" onNext={() => setStep(1)} />
            </div>
          )}
          {step === 1 &&
            (templates.isPending ? (
              <p role="status">Загружаем шаблоны…</p>
            ) : templates.isError && !templates.data ? (
              <div role="alert">
                <p>{errorMessage(templates.error)}</p>
                <Button onClick={() => void templates.refetch()}>
                  Повторить загрузку шаблонов
                </Button>
              </div>
            ) : !available.length ? (
              <p>Шаблонов пока нет. Обратитесь к команде проекта.</p>
            ) : (
              <>
                <label className="block space-y-2">
                  <span>Шаблон документа</span>
                  <select
                    value={selected}
                    disabled={pending}
                    onChange={(event) => setSlug(event.target.value)}
                    className="min-h-12 w-full min-w-0 rounded-xl border bg-secondary p-3"
                  >
                    {available.map((template) => (
                      <option key={template.slug} value={template.slug}>
                        {template.title}
                        {template.discipline ? ` — ${template.discipline}` : ''}
                      </option>
                    ))}
                  </select>
                </label>
                {detail.isPending ? (
                  <p role="status" className="py-4">
                    Загружаем поля шаблона…
                  </p>
                ) : detail.isError && !detail.data ? (
                  <div role="alert" className="space-y-3 py-4">
                    <p>{errorMessage(detail.error)}</p>
                    <Button onClick={() => void detail.refetch()}>Повторить загрузку полей</Button>
                  </div>
                ) : null}
              </>
            ))}
          {step === 1 && (
            <WizardButtons
              onBack={() => setStep(0)}
              onNext={() => setStep(2)}
              disabled={!detail.data || projects.isPending}
            />
          )}
          {detail.data && !projects.isPending && (
            <CreateForm
              key={detail.data.slug}
              template={detail.data}
              title={title}
              previous={previous}
              step={step}
              onStep={setStep}
              files={files}
              onFiles={setFiles}
              onTitle={setTitle}
              onPending={setPending}
              onClose={onClose}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function WizardButtons({
  onBack,
  onNext,
  backLabel = 'Назад',
  disabled,
}: {
  onBack: () => void;
  onNext: () => void;
  backLabel?: string;
  disabled?: boolean;
}) {
  return (
    <div className="mt-4 flex flex-wrap justify-end gap-3">
      <Button type="button" variant="outline" onClick={onBack}>
        {backLabel}
      </Button>
      <Button type="button" disabled={disabled} onClick={onNext}>
        Далее
      </Button>
    </div>
  );
}

function CreateForm({
  template,
  title,
  previous,
  step,
  onStep,
  files,
  onFiles,
  onTitle,
  onPending,
  onClose,
}: {
  template: components['schemas']['TemplateDetail'];
  title: string;
  previous?: components['schemas']['ProjectOut'];
  step: number;
  onStep: (step: number) => void;
  files: File[];
  onFiles: (files: File[]) => void;
  onTitle: (title: string) => void;
  onPending: (pending: boolean) => void;
  onClose: () => void;
}) {
  const prefix = useId();
  const client = useQueryClient();
  const navigate = useNavigate();
  const { data: session } = useSession();
  const owner = session?.user.id;
  const current = () =>
    Boolean(owner) &&
    client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id === owner;
  const [created, setCreated] = useState<string>();
  const [phase, setPhase] = useState<'create' | 'upload' | 'send'>();
  const [failed, setFailed] = useState<'upload' | 'send'>();
  const lock = useRef(false);
  const upload = useMaterialUpload();
  const send = useMutation({
    meta: { sessionUserId: owner },
    mutationFn: async ({ id, retry }: { id: string; retry: boolean }) => {
      if (retry) {
        // Ответ на POST мог потеряться после записи сообщения сервером.
        const history = await client.fetchQuery({
          queryKey: chatKey(id),
          queryFn: ({ signal }) => getMessages(id, signal),
          staleTime: 0,
        });
        if (
          history.items.some(
            (item) =>
              item.role === 'user' &&
              item.parts.some((part) => part.type === 'text' && part.text === firstMessage),
          )
        )
          return;
      }
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      await postChatMessage(id, firstMessage);
      void client.invalidateQueries({ queryKey: chatKey(id), exact: true });
    },
  });
  const form = useForm<ProjectForm>({
    resolver: zodResolver(createProjectSchema(template.fields)),
    defaultValues: {
      title,
      fields: Object.fromEntries(
        template.fields.map((field) => {
          const candidate = previous?.fields[field.key];
          const compatible =
            field.type === 'int'
              ? typeof candidate === 'number' && Number.isSafeInteger(candidate)
              : typeof candidate === 'string' &&
                (field.type === 'select'
                  ? field.options.includes(candidate)
                  : candidate.length <= (field.type === 'text' ? 10_000 : 200));
          return [field.key, String(compatible ? candidate : (field.default ?? ''))];
        }),
      ),
    },
  });
  const mutation = useMutation({
    meta: { formErrors: true, sessionUserId: owner },
    mutationFn: async (values: ProjectForm) => {
      if (!current())
        throw new ApiError(0, 'session_changed', 'Сессия изменилась. Войдите заново.');
      const { data } = await api.POST('/api/v1/projects', {
        body: {
          title: values.title,
          template_slug: template.slug,
          fields: projectFields(template.fields, values.fields),
        },
      });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил создание проекта.');
      return data;
    },
  });
  function openProject(id: string) {
    navigate(`/projects/${encodeURIComponent(id)}`);
    onClose();
  }
  async function submit(values: ProjectForm) {
    if (step === 2) {
      onStep(3);
      return;
    }
    if (step !== 3 || lock.current) return;
    lock.current = true;
    form.clearErrors();
    onPending(true);
    let projectId = created;
    let action: typeof phase = 'create';
    try {
      if (!projectId) {
        setPhase('create');
        const project = await mutation.mutateAsync(values);
        if (!current()) return;
        projectId = project.id;
        setCreated(projectId);
        client.setQueryData<components['schemas']['ProjectList']>(projectsKey, (previous) => ({
          items: [project, ...(previous?.items.filter((item) => item.id !== project.id) ?? [])],
        }));
        client.setQueryData(['projects', projectId], project);
        void client.invalidateQueries({ queryKey: projectsKey, exact: true });
      }
      if (files.length && failed !== 'send') {
        action = 'upload';
        setPhase(action);
        await upload.mutateAsync({ projectId, files, dir: 'materials' });
      }
      if (!current()) return;
      action = 'send';
      setPhase(action);
      await send.mutateAsync({ id: projectId, retry: failed === 'send' });
      if (current()) openProject(projectId);
    } catch (error) {
      if (!current()) return;
      if (action === 'upload' || action === 'send') {
        setFailed(action);
        form.setError('root.server', { message: errorMessage(error) });
        return;
      }
      let applied = false;
      if (error instanceof ApiError && Array.isArray(error.details.errors))
        for (const issue of error.details.errors) {
          if (
            !isRecord(issue) ||
            !Array.isArray(issue.loc) ||
            typeof issue.message !== 'string' ||
            issue.loc[0] !== 'body'
          )
            continue;
          const loc = issue.loc;
          const field =
            loc[1] === 'fields' && template.fields.some((field) => field.key === loc[2])
              ? (`fields.${String(issue.loc[2])}` as const)
              : issue.loc[1] === 'title'
                ? 'title'
                : undefined;
          if (field) {
            form.setError(field, { message: issue.message }, { shouldFocus: !applied });
            applied = true;
          }
        }
      if (applied) onStep(2);
      else form.setError('root.server', { message: errorMessage(error) });
    } finally {
      lock.current = false;
      setPhase(undefined);
      onPending(false);
    }
  }
  return (
    <form
      hidden={step < 2}
      noValidate
      onSubmit={(event) => void form.handleSubmit(submit)(event)}
      className="space-y-4"
    >
      <div hidden={step !== 2} className="space-y-4">
        {previous && (
          <p className="text-sm text-muted-foreground break-words">
            Данные предложены из проекта «{previous.title}».
          </p>
        )}
        <FormField
          label="Название проекта"
          hint={projectNameHint}
          maxLength={200}
          autoComplete="off"
          disabled={mutation.isPending}
          {...form.register('title', {
            onChange: (event: React.ChangeEvent<HTMLInputElement>) => onTitle(event.target.value),
          })}
          error={form.formState.errors.title?.message}
        />
        {template.fields.map((field) => {
          const id = `${prefix}-${field.key}`;
          const error = form.formState.errors.fields?.[field.key]?.message;
          const register = form.register(`fields.${field.key}`);
          const shared = {
            ...register,
            id,
            disabled: mutation.isPending,
            'aria-invalid': Boolean(error),
            'aria-describedby': `${id}-hint${error ? ` ${id}-error` : ''}`,
            className:
              'min-h-12 w-full min-w-0 rounded-xl border bg-secondary p-3 outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive',
          };
          return (
            <div key={field.key} className="space-y-2">
              <label htmlFor={id} className="block font-medium">
                {field.label}
                {field.required && ' *'}
              </label>
              <p id={`${id}-hint`} className="text-sm text-muted-foreground">
                {templateFieldHint(field)}
              </p>
              {field.type === 'select' ? (
                <select {...shared}>
                  <option value="">Выберите вариант</option>
                  {field.options.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              ) : field.type === 'text' ? (
                <textarea {...shared} rows={4} maxLength={10000} />
              ) : (
                <input
                  {...shared}
                  type="text"
                  inputMode={field.type === 'int' ? 'numeric' : 'text'}
                  maxLength={field.type === 'int' ? 100 : 200}
                />
              )}
              {error && (
                <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
            </div>
          );
        })}
      </div>
      {step === 3 && (
        <WizardMaterials
          files={files}
          onFiles={onFiles}
          disabled={Boolean(phase) || failed === 'send'}
        />
      )}
      {phase && (
        <p role="status" className="text-sm text-muted-foreground">
          {phase === 'create'
            ? 'Создаём проект…'
            : phase === 'send'
              ? 'Отправляем первый запрос…'
              : upload.progress.percent === null
                ? 'Загружаем материалы…'
                : `Загружаем материалы: ${upload.progress.percent}%`}
        </p>
      )}
      {created && failed && !phase && (
        <p className="text-sm text-muted-foreground">
          Проект уже создан.{' '}
          {failed === 'upload'
            ? 'Проверьте файлы и повторите загрузку.'
            : 'Повторите отправку запроса.'}
        </p>
      )}
      {form.formState.errors.root?.server?.message && (
        <p role="alert" className="text-sm text-destructive">
          {form.formState.errors.root.server.message}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3">
        {created ? (
          <Button
            type="button"
            variant="outline"
            disabled={Boolean(phase)}
            onClick={() => openProject(created)}
          >
            Открыть проект
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            disabled={Boolean(phase)}
            onClick={() => onStep(step - 1)}
          >
            Назад
          </Button>
        )}
        <Button type="submit" disabled={Boolean(phase)}>
          {step === 2
            ? 'Далее'
            : created && failed === 'upload'
              ? 'Продолжить загрузку'
              : created && failed === 'send'
                ? 'Повторить отправку'
                : 'Создать проект'}
        </Button>
      </div>
    </form>
  );
}
