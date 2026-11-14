import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { errorMessage } from '@/app/query-client';
import { FormField } from '@/components/form-field';
import { Button } from '@/components/ui/button';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { showFormError } from '@/lib/form-errors';
import { usageKey } from './usage-query';

const keySettings = ['settings', 'llm-key'] as const;
type KeySettings = components['schemas']['LlmKeySettings'];
type KeyInput = components['schemas']['LlmKeySave'];

export function LlmKeySettings() {
  const settings = useQuery({
    queryKey: keySettings,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/settings/llm-key', { signal });
      if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не прислал настройки ключа.');
      return data;
    },
  });
  return (
    <section
      className="max-w-2xl space-y-4 rounded-2xl border bg-secondary/50 p-5 sm:p-7"
      aria-labelledby="llm-key"
    >
      <h2 id="llm-key" className="text-xl font-bold">
        Ключ ИИ
      </h2>
      {settings.isPending ? (
        <p role="status">Загружаем настройки…</p>
      ) : settings.isError ? (
        <div role="alert" className="space-y-3">
          <p>{errorMessage(settings.error)}</p>
          <Button onClick={() => void settings.refetch()}>Повторить загрузку</Button>
        </div>
      ) : (
        <KeyForm settings={settings.data} />
      )}
    </section>
  );
}

function KeyForm({ settings }: { settings: KeySettings }) {
  const client = useQueryClient();
  const { data: session } = useSession();
  const owner = session?.user.id;
  const current = () =>
    Boolean(owner) &&
    client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id === owner;
  const form = useForm<KeyInput>({ defaultValues: { key: '' } });
  // Ключ не должен оставаться в переменных мутации в кэше.
  const pendingKey = useRef('');
  const update = useMutation({
    meta: { formErrors: true, sessionUserId: owner },
    mutationFn: async (action: 'save' | 'remove') => {
      const key = pendingKey.current;
      pendingKey.current = '';
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      if (action === 'remove') {
        await api.DELETE('/api/v1/settings/llm-key');
        return null;
      }
      const { data } = await api.PUT('/api/v1/settings/llm-key', { body: { key } });
      if (!data)
        throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил сохранение ключа.');
      return data;
    },
    onSuccess: async (key) => {
      if (!current()) return;
      await client.cancelQueries({ queryKey: keySettings });
      if (!current()) return;
      client.setQueryData<KeySettings>(keySettings, (previous) =>
        previous ? { ...previous, key } : undefined,
      );
      form.reset();
      void client.invalidateQueries({ queryKey: usageKey });
    },
  });
  const submitting = useRef(false);
  async function change(action: 'save' | 'remove', key = '') {
    if (submitting.current || (action === 'save' && !settings.provider)) return;
    submitting.current = true;
    form.clearErrors();
    pendingKey.current = key;
    try {
      await update.mutateAsync(action);
    } catch (error) {
      if (current()) showFormError(error, form.setError, ['key']);
    } finally {
      pendingKey.current = '';
      submitting.current = false;
    }
  }
  const { provider, key } = settings;
  const { errors } = form.formState;
  return (
    <form
      noValidate
      onSubmit={(event) => void form.handleSubmit(({ key }) => change('save', key.trim()))(event)}
      className="space-y-4"
      aria-busy={update.isPending}
    >
      <p>{provider ? `Провайдер: ${provider}` : 'ИИ на сервере пока не настроен.'}</p>
      <p>
        {key ? (
          <>
            Сохранённый ключ: <code>••••{key.last4}</code>
          </>
        ) : (
          'Ключ не добавлен.'
        )}
      </p>
      {key && key.provider !== provider && (
        <p className="text-muted-foreground">Ключ для {key.provider} больше не используется.</p>
      )}
      {provider && (
        <FormField
          label="Ключ API"
          type="password"
          autoComplete="new-password"
          spellCheck={false}
          disabled={update.isPending}
          {...form.register('key', {
            validate: (value) =>
              /^[!-~]{8,500}$/.test(value.trim()) || 'Введите от 8 до 500 символов без пробелов.',
          })}
          error={errors.key?.message}
        />
      )}
      {errors.root?.server && (
        <p role="alert" className="text-destructive">
          {errors.root.server.message}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        {provider && (
          <Button type="submit" disabled={update.isPending}>
            {key ? 'Заменить ключ' : 'Сохранить ключ'}
          </Button>
        )}
        {key && (
          <Button
            type="button"
            variant="outline"
            disabled={update.isPending}
            onClick={() => void change('remove')}
          >
            Удалить ключ
          </Button>
        )}
      </div>
      {update.isPending && (
        <p role="status">{update.variables === 'save' ? 'Проверяем ключ…' : 'Удаляем ключ…'}</p>
      )}
    </form>
  );
}
