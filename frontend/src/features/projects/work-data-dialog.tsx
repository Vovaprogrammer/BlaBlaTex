import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Dialog } from 'radix-ui';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { errorMessage } from '@/app/query-client';
import { ErrorState, LoadingState } from '@/components/screen-state';
import { Button } from '@/components/ui/button';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { useDraftStore } from '@/features/editor/draft-context';
import { workspaceKeys } from '@/features/workspace/workspace-queries';
import {
  applyTemplateFormErrors,
  defaultTemplateFields,
  projectFields,
  templateFieldsSchema,
  type TemplateFieldsForm,
} from './project-form';
import { projectsKey, useTemplateDetail } from './project-queries';
import { TemplateFields } from './template-fields';

type Project = components['schemas']['ProjectOut'];
type FieldValues = Project['fields'];

function sameFields(first: FieldValues, second: FieldValues) {
  const entries = Object.entries(first);
  return (
    entries.length === Object.keys(second).length &&
    entries.every(([name, value]) => Object.hasOwn(second, name) && second[name] === value)
  );
}

export function WorkDataDialog({
  project,
  locked,
  onClose,
  returnFocus,
}: {
  project: Project;
  locked: boolean;
  onClose: () => void;
  returnFocus: () => void;
}) {
  const template = useTemplateDetail(project.template_slug);
  const client = useQueryClient();
  const drafts = useDraftStore();
  const { data: session } = useSession();
  const owner = session?.user.id;
  const current = () =>
    owner !== undefined &&
    client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id === owner;
  const projectKey = workspaceKeys.project(project.id);
  const mutation = useMutation({
    meta: { formErrors: true, sessionUserId: owner },
    mutationFn: async ({ fields, initial }: { fields: FieldValues; initial: FieldValues }) => {
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      const params = { path: { pid: project.id } };
      const { data: latest } = await api.GET('/api/v1/projects/{pid}', { params });
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      if (!latest) throw new ApiError(0, 'invalid_response', 'Не удалось прочитать проект.');
      if (!sameFields(initial, latest.fields)) {
        void client.invalidateQueries({ queryKey: projectKey, exact: true });
        void client.invalidateQueries({ queryKey: projectsKey, exact: true });
        throw new ApiError(
          409,
          'work_data_changed',
          'Данные работы уже изменились. Откройте форму заново, чтобы увидеть актуальные значения.',
        );
      }
      const { data } = await api.PATCH('/api/v1/projects/{pid}', {
        params,
        body: { fields },
      });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил сохранение данных.');
      return data;
    },
    onSuccess: async (updated) => {
      if (!current()) return;
      await Promise.all([
        client.cancelQueries({ queryKey: projectsKey, exact: true }),
        client.cancelQueries({ queryKey: projectKey, exact: true }),
      ]);
      if (!current()) return;
      client.setQueryData(projectKey, updated);
      client.setQueryData<components['schemas']['ProjectList']>(
        projectsKey,
        (previous) =>
          previous && {
            items: previous.items.map((item) => (item.id === updated.id ? updated : item)),
          },
      );
      void drafts.refresh(project.id, 'meta.tex');
      void client.invalidateQueries({ queryKey: workspaceKeys.tree(project.id), exact: true });
      void client.invalidateQueries({ queryKey: projectsKey, exact: true });
      onClose();
    },
  });
  const pending = mutation.isPending;
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
          className="fixed left-1/2 top-1/2 z-50 max-h-[90svh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border bg-card p-6 shadow-xl"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            returnFocus();
          }}
        >
          <Dialog.Title className="text-xl font-semibold">Данные работы</Dialog.Title>
          <Dialog.Description className="my-4 text-sm text-muted-foreground">
            Чтобы обновить титульный лист, после сохранения нажмите «Собрать PDF».
          </Dialog.Description>
          {template.data ? (
            <WorkDataForm
              fields={template.data.fields}
              initial={project.fields}
              locked={locked}
              pending={pending}
              save={async (fields, initial) => {
                await mutation.mutateAsync({ fields, initial });
              }}
              onClose={onClose}
            />
          ) : template.isError ? (
            <ErrorState
              error={template.error}
              retry={() => void template.refetch()}
              retrying={template.isFetching}
            />
          ) : (
            <LoadingState>Загружаем поля шаблона…</LoadingState>
          )}
          {!template.data && (
            <Button className="mt-4" variant="outline" onClick={onClose}>
              Отмена
            </Button>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function WorkDataForm({
  fields,
  initial,
  locked,
  pending,
  save,
  onClose,
}: {
  fields: components['schemas']['TemplateField'][];
  initial: Project['fields'];
  locked: boolean;
  pending: boolean;
  save: (fields: FieldValues, initial: FieldValues) => Promise<void>;
  onClose: () => void;
}) {
  const [initialFields] = useState(() => ({ ...initial }));
  const [rejectedField, setRejectedField] = useState<`fields.${string}`>();
  const form = useForm<TemplateFieldsForm>({
    resolver: zodResolver(templateFieldsSchema(fields)),
    defaultValues: { fields: defaultTemplateFields(fields, initialFields) },
  });
  const { errors, isSubmitting } = form.formState;
  const { setFocus } = form;
  useEffect(() => {
    if (!pending && rejectedField) setFocus(rejectedField);
  }, [pending, rejectedField, setFocus]);
  async function submit(values: TemplateFieldsForm) {
    if (pending || locked) return;
    form.clearErrors();
    setRejectedField(undefined);
    try {
      await save(projectFields(fields, values.fields), initialFields);
    } catch (error) {
      let applied = false;
      applyTemplateFormErrors(error, fields, (name, message) => {
        if (name === 'title') return;
        form.setError(name, { message });
        if (!applied) setRejectedField(name);
        applied = true;
      });
      if (!applied) form.setError('root.server', { message: errorMessage(error) });
    }
  }
  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(event) => void form.handleSubmit(submit)(event)}
    >
      <TemplateFields
        fields={fields}
        register={form.register}
        errors={errors.fields}
        disabled={pending}
      />
      {locked && (
        <p role="status" className="text-sm">
          Сохранение доступно после завершения работы помощника.
        </p>
      )}
      {errors.root?.server?.message && (
        <p role="alert" className="text-sm text-destructive">
          {errors.root.server.message}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3">
        <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
          Отмена
        </Button>
        <Button type="submit" disabled={pending || isSubmitting || locked}>
          {pending ? 'Сохраняем…' : 'Сохранить изменения'}
        </Button>
      </div>
    </form>
  );
}
