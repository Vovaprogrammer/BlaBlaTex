import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { AlertDialog } from 'radix-ui';
import { toast } from 'sonner';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { errorMessage } from '@/app/query-client';
import { FormField } from '@/components/form-field';
import { Button } from '@/components/ui/button';
import { replaceSession } from '@/features/auth/session-actions';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { showFormError } from '@/lib/form-errors';
import { textLinkClass } from '@/lib/utils';

type Values = { password: string };
type MeResponse = components['schemas']['MeResponse'];

export function DeleteAccount() {
  const { data: session } = useSession();
  return (
    session && (
      <DeleteAccountSection
        key={session.user.id}
        owner={session.user.id}
        email={session.user.email}
      />
    )
  );
}

function DeleteAccountSection({ owner, email }: { owner: string; email: string }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  // Прогон, из-за которого сервер не дал удалить аккаунт (423): его можно остановить отсюда.
  const [busyRun, setBusyRun] = useState<string>();
  const form = useForm<Values>({ defaultValues: { password: '' } });
  const remove = useMutation({
    meta: { sessionUserId: owner, inlineErrors: true },
    mutationFn: async ({ password }: Values) => {
      // Удаляем только аккаунт, который назван в диалоге.
      if (client.getQueryData<MeResponse | null>(sessionKey)?.user.id !== owner)
        throw new ApiError(0, 'session_changed', 'Сессия изменилась. Войдите заново.');
      await api.DELETE('/api/v1/account', { body: { password } });
    },
    onSuccess: async () => {
      await replaceSession(client, null);
      toast.success('Аккаунт удалён');
      navigate('/login', { replace: true });
    },
  });
  const stop = useMutation({
    meta: { sessionUserId: owner, inlineErrors: true },
    mutationFn: async (rid: string) => {
      await api.POST('/api/v1/runs/{rid}/cancel', { params: { path: { rid } } });
    },
    onSuccess: () => {
      // Ответ 423 больше не про текущее состояние: ИИ уже останавливается.
      setBusyRun(undefined);
      form.clearErrors('root');
    },
  });
  const pending = remove.isPending || stop.isPending;
  const { errors } = form.formState;
  const submit = form.handleSubmit(async (values) => {
    form.clearErrors();
    setBusyRun(undefined);
    stop.reset();
    try {
      await remove.mutateAsync(values);
    } catch (error) {
      if (error instanceof ApiError && error.status === 423) {
        const rid = error.details.run_id;
        if (typeof rid === 'string') setBusyRun(rid);
      }
      showFormError(error, form.setError, ['password']);
    }
  });
  function close() {
    setOpen(false);
    setBusyRun(undefined);
    form.reset();
    remove.reset();
    stop.reset();
  }
  return (
    <section
      aria-labelledby="delete-account"
      className="max-w-2xl min-w-0 space-y-4 rounded-2xl border border-destructive/40 bg-secondary/50 p-5 sm:p-7"
    >
      <h2 id="delete-account" className="text-xl font-bold">
        Удаление аккаунта
      </h2>
      <p className="text-sm text-muted-foreground">
        Удалятся профиль и все проекты — с файлами, материалами, историей правок, чатом и сборками,
        — а ещё личные токены и ключ ИИ. Вернуть их нельзя. Нужные проекты сначала скачайте: меню
        проекта «⋯» → «Скачать исходники ZIP».
      </p>
      <p className="text-sm text-muted-foreground">
        Что ещё какое-то время остаётся в резервных копиях и журналах сервера, сказано в{' '}
        <Link to="/privacy" className={textLinkClass}>
          политике конфиденциальности
        </Link>
        .
      </p>
      <Button variant="destructive" onClick={() => setOpen(true)}>
        Удалить аккаунт
      </Button>
      {open && (
        <AlertDialog.Root
          open
          onOpenChange={(next) => {
            if (!next && !pending) close();
          }}
        >
          <AlertDialog.Portal>
            <AlertDialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
            <AlertDialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl border bg-card p-6">
              <form noValidate onSubmit={(event) => void submit(event)} className="space-y-4">
                <AlertDialog.Title className="text-xl font-semibold">
                  Удалить аккаунт?
                </AlertDialog.Title>
                <AlertDialog.Description className="break-words text-sm text-muted-foreground">
                  Аккаунт {email} и все его проекты удалятся без возврата. Введите пароль, чтобы
                  подтвердить.
                </AlertDialog.Description>
                <FormField
                  label="Пароль"
                  type="password"
                  autoComplete="current-password"
                  disabled={pending}
                  {...form.register('password', { required: 'Введите пароль' })}
                  error={errors.password?.message}
                />
                {errors.root?.server && (
                  <p role="alert" className="break-words text-sm text-destructive">
                    {errors.root.server.message}
                  </p>
                )}
                {busyRun && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={pending}
                    onClick={() => stop.mutate(busyRun)}
                  >
                    {stop.isPending ? 'Останавливаем…' : 'Остановить ИИ'}
                  </Button>
                )}
                {stop.isSuccess && (
                  <p role="status" className="text-sm">
                    ИИ останавливается. Через несколько секунд повторите удаление.
                  </p>
                )}
                {stop.isError && (
                  <p role="alert" className="break-words text-sm text-destructive">
                    {errorMessage(stop.error)}
                  </p>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  <AlertDialog.Cancel asChild>
                    <Button type="button" variant="outline" disabled={pending}>
                      Отмена
                    </Button>
                  </AlertDialog.Cancel>
                  <Button type="submit" variant="destructive" disabled={pending}>
                    {remove.isPending ? 'Удаляем…' : 'Удалить навсегда'}
                  </Button>
                </div>
              </form>
            </AlertDialog.Content>
          </AlertDialog.Portal>
        </AlertDialog.Root>
      )}
    </section>
  );
}
