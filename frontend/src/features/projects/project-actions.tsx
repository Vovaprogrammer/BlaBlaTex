import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Dialog, DropdownMenu } from 'radix-ui';
import { MoreHorizontal } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/form-field';
import { errorMessage } from '@/app/query-client';
import { showFormError } from '@/lib/form-errors';
import { useDraftRevision, useDraftStore } from '@/features/editor/draft-context';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { projectTitle } from './project-form';
import { projectsKey } from './project-queries';
import { projectNameHint } from './project-field-hints';

type Project = components['schemas']['ProjectOut'];
const schema = z.object({ title: projectTitle });
export function ProjectActions({ project }: { project: Project }) {
  const [action, setAction] = useState<'rename' | 'delete' | null>(null);
  return (
    <>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <Button variant="ghost" size="icon" aria-label={`Действия с проектом «${project.title}»`}>
            <MoreHorizontal />
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            className="z-40 min-w-48 rounded-xl border bg-card p-1 shadow-xl"
          >
            <DropdownMenu.Item
              onSelect={() => setAction('rename')}
              className="cursor-pointer rounded-lg px-3 py-2 outline-none data-[highlighted]:bg-accent"
            >
              Переименовать проект
            </DropdownMenu.Item>
            <DropdownMenu.Item
              onSelect={() => setAction('delete')}
              className="cursor-pointer rounded-lg px-3 py-2 text-destructive outline-none data-[highlighted]:bg-accent"
            >
              Удалить проект
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      {action && (
        <ProjectActionForm
          key={action}
          project={project}
          action={action}
          onClose={() => setAction(null)}
        />
      )}
    </>
  );
}

function ProjectActionForm({
  project,
  action,
  onClose,
}: {
  project: Project;
  action: 'rename' | 'delete';
  onClose: () => void;
}) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const { data: session } = useSession();
  const drafts = useDraftStore();
  useDraftRevision();
  const blocked =
    action === 'delete' && drafts.pending().some((draft) => draft.project === project.id);
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { title: project.title },
  });
  const mutation = useMutation({
    meta: { formErrors: true, sessionUserId: session?.user.id },
    mutationFn: async (title: string) => {
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
        throw new ApiError(0, 'session_changed', 'Сессия изменилась. Войдите заново.');
      if (action === 'delete') {
        if (drafts.pending().some((draft) => draft.project === project.id))
          throw new ApiError(
            0,
            'unsaved_changes',
            'Сначала сохраните изменения в файлах или разрешите конфликт.',
          );
        await api.DELETE('/api/v1/projects/{pid}', { params: { path: { pid: project.id } } });
        return null;
      }
      const { data } = await api.PATCH('/api/v1/projects/{pid}', {
        params: { path: { pid: project.id } },
        body: { title },
      });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил переименование проекта.');
      return data;
    },
    onSuccess: async (updated) => {
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
        return;
      await client.cancelQueries({ queryKey: projectsKey, exact: true });
      if (
        client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
        session?.user.id
      )
        return;
      client.setQueryData<components['schemas']['ProjectList']>(projectsKey, (previous) =>
        previous
          ? {
              items: updated
                ? previous.items.map((item) => (item.id === project.id ? updated : item))
                : previous.items.filter((item) => item.id !== project.id),
            }
          : previous,
      );
      if (updated) {
        client.setQueryData(['projects', project.id], updated);
        void client.invalidateQueries({ queryKey: ['projects', project.id] });
      } else {
        drafts.removeProject(project.id);
        navigate('/projects', { replace: true });
        client.removeQueries({ queryKey: ['projects', project.id] });
        for (const query of client.getQueryCache().findAll({ queryKey: ['builds'] })) {
          if (
            query.queryKey.length === 2 &&
            client.getQueryData<components['schemas']['BuildOut']>(query.queryKey)?.project_id ===
              project.id
          )
            client.removeQueries({ queryKey: query.queryKey });
        }
      }
      void client.invalidateQueries({ queryKey: projectsKey, exact: true });
      onClose();
    },
  });
  const pending = mutation.isPending || form.formState.isSubmitting;
  const rename = form.handleSubmit(async (values) => {
    form.clearErrors();
    try {
      await mutation.mutateAsync(values.title);
    } catch (error) {
      showFormError(error, form.setError, ['title']);
    }
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
          className="fixed left-1/2 top-1/2 z-50 max-h-[90svh] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border bg-card p-6 shadow-xl"
          onEscapeKeyDown={(event) => {
            if (pending) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (pending) event.preventDefault();
          }}
        >
          <Dialog.Title className="text-xl font-semibold">
            {action === 'rename' ? 'Переименовать проект' : 'Удалить проект'}
          </Dialog.Title>
          <Dialog.Description className="my-4 break-words text-sm text-muted-foreground">
            {action === 'rename'
              ? 'Изменится название проекта. Его файлы останутся на месте.'
              : `Удалить «${project.title}» вместе со всеми файлами? Это действие нельзя отменить.`}
          </Dialog.Description>
          <form
            noValidate
            className="space-y-5"
            onSubmit={(event) => {
              if (action === 'rename') void rename(event);
              else {
                event.preventDefault();
                if (!pending && !blocked) mutation.mutate(project.title);
              }
            }}
          >
            {action === 'rename' && (
              <FormField
                label="Название проекта"
                hint={projectNameHint}
                maxLength={200}
                disabled={pending}
                {...form.register('title')}
                error={form.formState.errors.title?.message}
              />
            )}
            {blocked && (
              <p role="alert" className="text-sm text-destructive">
                Сначала сохраните изменения в файлах или разрешите конфликт.
              </p>
            )}
            {(action === 'delete'
              ? mutation.error
              : form.formState.errors.root?.server?.message) && (
              <p role="alert" className="text-sm text-destructive">
                {action === 'delete'
                  ? errorMessage(mutation.error)
                  : form.formState.errors.root?.server?.message}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-3">
              <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
                Отмена
              </Button>
              <Button
                type="submit"
                variant={action === 'delete' ? 'destructive' : 'default'}
                disabled={pending || blocked}
              >
                {pending
                  ? 'Сохраняем…'
                  : action === 'delete'
                    ? 'Удалить проект'
                    : 'Сохранить название'}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
