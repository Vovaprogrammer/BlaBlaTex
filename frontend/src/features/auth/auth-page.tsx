import { LockKeyhole, Mail, UserRound } from 'lucide-react';
import { Link, useLocation, useNavigate } from 'react-router';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/form-field';
import { showFormError } from '@/lib/form-errors';
import { authSchema, type AuthValues } from './auth-schema';
import { replaceSession, returnPath } from './session-actions';

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  return <AuthForm key={mode} register={mode === 'register'} />;
}

function AuthForm({ register }: { register: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const form = useForm<AuthValues>({
    resolver: zodResolver(authSchema(register)),
    defaultValues: { email: '', password: '', confirmPassword: '', consent: false },
  });
  const mutation = useMutation({
    meta: { formErrors: true, authForm: true },
    mutationFn: async (values: AuthValues) => {
      const body = { email: values.email, password: values.password };
      const response = register
        ? await api.POST('/api/v1/auth/register', { body: { ...body, consent: true } })
        : await api.POST('/api/v1/auth/login', { body });
      if (!response.data)
        throw new ApiError(
          0,
          'invalid_response',
          'Сервер вернул пустой ответ. Попробуйте ещё раз.',
        );
      return response.data;
    },
    onSuccess: async (session) => {
      await replaceSession(client, session);
      navigate(register ? '/profile' : returnPath(location.state), { replace: true });
    },
  });
  const { errors, isSubmitting } = form.formState;
  const submit = form.handleSubmit(async (values) => {
    form.clearErrors();
    try {
      await mutation.mutateAsync(values);
    } catch (error) {
      if (register && error instanceof ApiError && error.status === 409)
        form.setError('email', { type: 'server', message: error.message }, { shouldFocus: true });
      else showFormError(error, form.setError, ['email', 'password', 'consent']);
    }
  });
  return (
    <div className="space-y-8">
      <header className="flex items-center gap-4">
        <span className="flex size-14 shrink-0 items-center justify-center rounded-full border border-ring bg-primary">
          <UserRound className="size-8 text-primary-foreground" aria-hidden="true" />
        </span>
        <div>
          <h1 className="text-2xl font-semibold">
            {register ? 'Создать аккаунт' : 'Войти в аккаунт'}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {register ? 'Начните работу над отчётом' : 'Продолжите работу над отчётом'}
          </p>
        </div>
      </header>
      <form
        noValidate
        onSubmit={(event) => void submit(event)}
        className="space-y-5"
        aria-busy={isSubmitting}
      >
        <fieldset disabled={isSubmitting} className="min-w-0 space-y-5">
          <legend className="sr-only">
            {register ? 'Данные для регистрации' : 'Данные для входа'}
          </legend>
          <FormField
            label="Email"
            icon={Mail}
            pale
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            {...form.register('email')}
            error={errors.email?.message}
          />
          <FormField
            label="Пароль"
            icon={LockKeyhole}
            pale
            type="password"
            autoComplete={register ? 'new-password' : 'current-password'}
            {...form.register('password')}
            error={errors.password?.message}
          />
          {register && (
            <>
              <FormField
                label="Повторите пароль"
                icon={LockKeyhole}
                pale
                type="password"
                autoComplete="new-password"
                {...form.register('confirmPassword')}
                error={errors.confirmPassword?.message}
              />
              <label className="flex items-start gap-3 text-sm leading-relaxed">
                <input
                  type="checkbox"
                  className="mt-1 size-4 shrink-0 accent-primary"
                  {...form.register('consent')}
                  aria-invalid={Boolean(errors.consent)}
                  aria-describedby={errors.consent ? 'consent-error' : undefined}
                />
                <span>Я согласен на обработку персональных данных</span>
              </label>
              {errors.consent && (
                <p role="alert" id="consent-error" className="text-sm text-destructive">
                  {errors.consent.message}
                </p>
              )}
              <details className="text-sm text-muted-foreground">
                <summary className="cursor-pointer text-ring underline underline-offset-4">
                  Текст согласия
                </summary>
                <p className="mt-2">
                  Полный текст согласия будет опубликован перед запуском сервиса. Сейчас здесь
                  временная заглушка.
                </p>
              </details>
            </>
          )}
        </fieldset>
        {errors.root?.server && (
          <p role="alert" className="text-sm text-destructive">
            {errors.root.server.message}
          </p>
        )}
        <Button
          type="submit"
          disabled={isSubmitting}
          className="min-h-14 w-full rounded-2xl border border-ring text-base"
        >
          {isSubmitting ? 'Подождите…' : register ? 'Зарегистрироваться' : 'Войти'}
        </Button>
      </form>
      <p className="text-center text-sm">
        {register ? 'Уже есть аккаунт?' : 'Нет аккаунта?'}{' '}
        <Link
          to={register ? '/login' : '/register'}
          state={location.state}
          className="rounded text-ring underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
        >
          {register ? 'Войти' : 'Зарегистрироваться'}
        </Link>
      </p>
    </div>
  );
}
