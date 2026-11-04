import { useState, useId } from 'react';
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
import { projectsKey } from './project-queries';
import { createProjectSchema, projectFields, type ProjectForm } from './project-form';

export function CreateProject({ onClose }: { onClose: () => void }) {
  const [slug, setSlug] = useState('');
  const [pending, setPending] = useState(false);
  const [title, setTitle] = useState('');
  const templates = useQuery({
    queryKey: ['templates'],
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/templates', { signal });
      if (!data) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать шаблоны.');
      return data;
    },
  });
  const selected = slug || templates.data?.items[0]?.slug || '';
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
          <Dialog.Description className="my-3 text-sm text-muted-foreground">
            Выберите шаблон и заполните данные документа. Данные об обучении берутся из вашего
            профиля.
          </Dialog.Description>
          {templates.isPending ? (
            <p role="status">Загружаем шаблоны…</p>
          ) : templates.isError && !templates.data ? (
            <div role="alert">
              <p>{errorMessage(templates.error)}</p>
              <Button onClick={() => void templates.refetch()}>Повторить загрузку шаблонов</Button>
            </div>
          ) : !templates.data?.items.length ? (
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
                  {templates.data.items.map((template) => (
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
              ) : (
                detail.data && (
                  <CreateForm
                    key={detail.data.slug}
                    template={detail.data}
                    title={title}
                    onTitle={setTitle}
                    onPending={setPending}
                    onClose={onClose}
                  />
                )
              )}
            </>
          )}
          {(!detail.data || (templates.isError && !templates.data)) && (
            <Button className="mt-4" variant="outline" disabled={pending} onClick={onClose}>
              Отмена
            </Button>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function CreateForm({
  template,
  title,
  onTitle,
  onPending,
  onClose,
}: {
  template: components['schemas']['TemplateDetail'];
  title: string;
  onTitle: (title: string) => void;
  onPending: (pending: boolean) => void;
  onClose: () => void;
}) {
  const prefix = useId();
  const client = useQueryClient();
  const navigate = useNavigate();
  const { data: session } = useSession();
  const form = useForm<ProjectForm>({
    resolver: zodResolver(createProjectSchema(template.fields)),
    defaultValues: {
      title,
      fields: Object.fromEntries(
        template.fields.map((field) => [field.key, String(field.default ?? '')]),
      ),
    },
  });
  const mutation = useMutation({
    meta: { formErrors: true, sessionUserId: session?.user.id },
    mutationFn: async (values: ProjectForm) => {
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
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
  const submit = form.handleSubmit(async (values) => {
    form.clearErrors();
    onPending(true);
    try {
      const project = await mutation.mutateAsync(values);
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
        return;
      client.setQueryData<components['schemas']['ProjectList']>(projectsKey, (previous) =>
        previous
          ? { items: [project, ...previous.items.filter((item) => item.id !== project.id)] }
          : { items: [project] },
      );
      client.setQueryData(['projects', project.id], project);
      void client.invalidateQueries({ queryKey: projectsKey, exact: true });
      navigate(`/projects/${encodeURIComponent(project.id)}`);
      onClose();
    } catch (error) {
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
      if (!applied) form.setError('root.server', { message: errorMessage(error) });
    } finally {
      onPending(false);
    }
  });
  return (
    <form noValidate onSubmit={(event) => void submit(event)} className="mt-5 space-y-5">
      <FormField
        label="Название проекта"
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
          'aria-describedby': error ? `${id}-error` : undefined,
          className:
            'min-h-12 w-full min-w-0 rounded-xl border bg-secondary p-3 outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive',
        };
        return (
          <div key={field.key} className="space-y-2">
            <label htmlFor={id} className="block font-medium">
              {field.label}
              {field.required && ' *'}
            </label>
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
      {form.formState.errors.root?.server?.message && (
        <p role="alert" className="text-sm text-destructive">
          {form.formState.errors.root.server.message}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3">
        <Button type="button" variant="outline" disabled={mutation.isPending} onClick={onClose}>
          Отмена
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Создаём…' : 'Создать проект'}
        </Button>
      </div>
    </form>
  );
}
