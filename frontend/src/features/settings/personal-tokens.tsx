import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertDialog } from 'radix-ui';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { errorMessage } from '@/app/query-client';
import { FormField } from '@/components/form-field';
import { ErrorState, LoadingState } from '@/components/screen-state';
import { Button } from '@/components/ui/button';
import { sessionKey, useSession } from '@/features/auth/use-session';

type Token = components['schemas']['ApiTokenOut'];
type TokenList = components['schemas']['ApiTokenList'];
const formatDate = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });

export function PersonalTokens() {
  const { data: session } = useSession();
  return session && <TokenSettings key={session.user.id} owner={session.user.id} />;
}

function TokenSettings({ owner }: { owner: string }) {
  const client = useQueryClient();
  const queryKey = ['settings', 'tokens', owner] as const;
  const current = () =>
    client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id === owner;
  const [name, setName] = useState('');
  const [secret, setSecret] = useState<{ id: string; value: string }>();
  const [toRevoke, setToRevoke] = useState<Token>();
  const tokens = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/tokens', { signal });
      if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не прислал список токенов.');
      return data;
    },
  });
  const create = useMutation({
    meta: { sessionUserId: owner, inlineErrors: true },
    mutationFn: async (name: string) => {
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      const { data } = await api.POST('/api/v1/tokens', { body: { name: name.trim() || null } });
      if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не прислал созданный токен.');
      const { token, ...item } = data;
      await client.cancelQueries({ queryKey, exact: true });
      if (!current()) return;
      // Полное значение остаётся только в состоянии открытого экрана.
      setSecret({ id: item.id, value: token });
      setName('');
      client.setQueryData<TokenList>(queryKey, (previous) => ({
        items: [item, ...(previous?.items ?? []).filter((row) => row.id !== item.id)],
      }));
      void client.invalidateQueries({ queryKey, exact: true });
    },
  });
  const revoke = useMutation({
    meta: { sessionUserId: owner, inlineErrors: true },
    mutationFn: async (id: string) => {
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      try {
        await api.DELETE('/api/v1/tokens/{tid}', { params: { path: { tid: id } } });
      } catch (error) {
        if (current() && error instanceof ApiError && error.status === 404)
          void client.invalidateQueries({ queryKey, exact: true });
        throw error;
      }
      await client.cancelQueries({ queryKey, exact: true });
      if (!current()) return;
      client.setQueryData<TokenList>(
        queryKey,
        (previous) => previous && { items: previous.items.filter((item) => item.id !== id) },
      );
      setToRevoke(undefined);
      setSecret((previous) => (previous?.id === id ? undefined : previous));
      void client.invalidateQueries({ queryKey, exact: true });
    },
  });
  return (
    <section
      aria-labelledby="personal-tokens"
      className="max-w-2xl min-w-0 space-y-4 rounded-2xl border bg-secondary/50 p-5 sm:p-7"
    >
      <h2 id="personal-tokens" className="text-xl font-bold">
        Личные токены
      </h2>
      <p className="text-sm text-muted-foreground">
        Токен даёт приложению или скрипту доступ к вашим проектам.
      </p>
      {tokens.isError && (
        <ErrorState
          error={tokens.error}
          retry={() => void tokens.refetch()}
          retrying={tokens.isFetching}
        />
      )}
      {tokens.isPending && <LoadingState>Загружаем токены…</LoadingState>}
      {tokens.data &&
        (tokens.data.items.length ? (
          <ul aria-label="Активные токены" className="divide-y rounded-xl border bg-card px-3">
            {tokens.data.items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div className="min-w-0 break-words">
                  <p className="font-medium">{item.name}</p>
                  <p className="text-xs text-muted-foreground">
                    Создан:{' '}
                    <time dateTime={item.created_at}>
                      {formatDate.format(new Date(item.created_at))}
                    </time>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {item.last_used_at ? (
                      <>
                        Последнее использование:{' '}
                        <time dateTime={item.last_used_at}>
                          {formatDate.format(new Date(item.last_used_at))}
                        </time>
                      </>
                    ) : (
                      'Ещё не использовался'
                    )}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`Отозвать токен «${item.name}»`}
                  onClick={() => {
                    revoke.reset();
                    setToRevoke(item);
                  }}
                >
                  Отозвать
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Личных токенов пока нет.</p>
        ))}
      {secret ? (
        <TokenSecret value={secret.value} onClose={() => setSecret(undefined)} />
      ) : (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!create.isPending) create.mutate(name);
          }}
        >
          <FormField
            label="Название токена (необязательно)"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            maxLength={100}
            disabled={create.isPending}
          />
          {create.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(create.error)}
            </p>
          )}
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? 'Создаём…' : 'Создать токен'}
          </Button>
        </form>
      )}
      {toRevoke && (
        <AlertDialog.Root
          open
          onOpenChange={(open) => {
            if (!open && !revoke.isPending) setToRevoke(undefined);
          }}
        >
          <AlertDialog.Portal>
            <AlertDialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
            <AlertDialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 space-y-4 rounded-2xl border bg-card p-6">
              <AlertDialog.Title className="text-xl font-semibold">
                Отозвать токен
              </AlertDialog.Title>
              <AlertDialog.Description className="break-words text-sm text-muted-foreground">
                Токен «{toRevoke.name}» сразу перестанет работать.
              </AlertDialog.Description>
              {revoke.isError && (
                <p role="alert" className="text-sm text-destructive">
                  {errorMessage(revoke.error)}
                </p>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                <AlertDialog.Cancel asChild>
                  <Button variant="outline" disabled={revoke.isPending}>
                    Отмена
                  </Button>
                </AlertDialog.Cancel>
                <Button
                  variant="destructive"
                  disabled={revoke.isPending}
                  onClick={() => revoke.mutate(toRevoke.id)}
                >
                  {revoke.isPending ? 'Отзываем…' : 'Отозвать токен'}
                </Button>
              </div>
            </AlertDialog.Content>
          </AlertDialog.Portal>
        </AlertDialog.Root>
      )}
    </section>
  );
}

function TokenSecret({ value, onClose }: { value: string; onClose: () => void }) {
  const [copyStatus, setCopyStatus] = useState<'copied' | 'failed'>();
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopyStatus('copied');
    } catch {
      setCopyStatus('failed');
    }
  }
  return (
    <div className="space-y-3 rounded-xl border border-ring bg-card p-4">
      <h3 className="font-semibold">Токен создан</h3>
      <p className="text-sm text-muted-foreground">
        Скопируйте токен сейчас. После закрытия его нельзя будет посмотреть снова.
      </p>
      <FormField
        readOnly
        label="Значение нового токена"
        value={value}
        className="font-mono"
        onFocus={(event) => event.currentTarget.select()}
      />
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void copy()}>Скопировать</Button>
        <Button variant="outline" onClick={onClose}>
          Закрыть значение токена
        </Button>
      </div>
      {copyStatus === 'copied' && (
        <p role="status" className="text-sm">
          Токен скопирован
        </p>
      )}
      {copyStatus === 'failed' && (
        <p role="alert" className="text-sm text-destructive">
          Не удалось скопировать. Выделите значение и скопируйте его вручную.
        </p>
      )}
    </div>
  );
}
