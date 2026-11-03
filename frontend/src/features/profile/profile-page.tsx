import { useState } from 'react';
import { BookOpen, Check, GraduationCap, Mail, Pencil, UserRound } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { api } from '@/api/client';
import type { components } from '@/api/schema';
import { ApiError } from '@/api/api-error';
import { errorMessage } from '@/app/query-client';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/form-field';
import { showFormError } from '@/lib/form-errors';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { profileFields, profileSchema } from './profile-schema';

type Profile = components['schemas']['ProfileOut'];
type ProfileInput = components['schemas']['ProfileUpdate'];
const profileKey = ['profile'] as const;

export function ProfilePage() {
  const profile = useQuery({
    queryKey: profileKey,
    queryFn: async ({ signal }) => {
      const { data } = await api.GET('/api/v1/profile', { signal });
      if (!data)
        throw new ApiError(
          0,
          'invalid_response',
          'Сервер вернул пустой профиль. Попробуйте ещё раз.',
        );
      return data;
    },
  });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold sm:text-4xl">Профиль</h1>
        <p className="mt-2 text-lg text-muted-foreground">Личная информация и данные об обучении</p>
      </header>
      {profile.isPending ? (
        <p role="status">Загружаем профиль…</p>
      ) : profile.isError ? (
        <div role="alert" className="space-y-4">
          <p>{errorMessage(profile.error)}</p>
          <Button onClick={() => void profile.refetch()}>Повторить</Button>
        </div>
      ) : (
        <ProfileContent profile={profile.data} />
      )}
    </div>
  );
}

function ProfileContent({ profile }: { profile: Profile }) {
  const client = useQueryClient();
  const { data: session } = useSession();
  const [editing, setEditing] = useState(() => profileFields.every(([key]) => !profile[key]));
  const [saved, setSaved] = useState(false);
  const form = useForm<ProfileInput>({
    resolver: zodResolver(profileSchema),
    defaultValues: profile,
  });
  const mutation = useMutation({
    meta: { formErrors: true },
    mutationFn: async (body: ProfileInput) => {
      const { data } = await api.PUT('/api/v1/profile', { body });
      if (!data)
        throw new ApiError(
          0,
          'invalid_response',
          'Сервер вернул пустой профиль. Попробуйте ещё раз.',
        );
      return data;
    },
    onSuccess: (data) => {
      const current = client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey);
      if (!current || current.user.id !== session?.user.id) return;
      client.setQueryData(profileKey, data);
      client.setQueryData<components['schemas']['MeResponse'] | null>(sessionKey, (previous) =>
        previous ? { ...previous, profile: data } : previous,
      );
      void client.invalidateQueries({
        predicate: (query) => !['session', 'profile'].includes(String(query.queryKey[0])),
      });
      form.reset(data);
      setEditing(false);
      setSaved(true);
    },
  });
  const fullName = [profile.last_name, profile.first_name, profile.middle_name]
    .filter(Boolean)
    .join(' ');
  const role = session?.user.role
    ? { student: 'Студент', teacher: 'Преподаватель', admin: 'Администратор' }[session.user.role]
    : '';
  const { errors, isSubmitting } = form.formState;
  const submit = form.handleSubmit(async (values) => {
    form.clearErrors();
    try {
      await mutation.mutateAsync(values);
    } catch (error) {
      showFormError(
        error,
        form.setError,
        profileFields.map(([key]) => key),
      );
    }
  });
  return (
    <>
      <section
        className="flex flex-col items-start gap-5 rounded-2xl border bg-secondary p-5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-7 sm:p-7"
        aria-label="Пользователь"
      >
        <span className="flex size-20 shrink-0 items-center justify-center rounded-full border-2 border-ring bg-primary sm:size-24">
          <UserRound className="size-12 text-primary-foreground" aria-hidden="true" />
        </span>
        <div className="min-w-0 w-full space-y-2 sm:w-auto sm:flex-1 sm:border-l sm:pl-7">
          <h2 className="break-words text-2xl font-bold">{fullName || 'Заполните профиль'}</h2>
          <p className="flex items-center gap-2 text-muted-foreground">
            <GraduationCap className="size-5 shrink-0" aria-hidden="true" />
            {role ? `Профиль: ${role.toLowerCase()}` : 'Данные для титульного листа'}
          </p>
        </div>
        {!editing && (
          <Button
            onClick={() => {
              form.reset(profile);
              setSaved(false);
              setEditing(true);
            }}
            className="min-h-12 rounded-xl border border-ring"
          >
            <Pencil aria-hidden="true" />
            Изменить профиль
          </Button>
        )}
      </section>
      <form
        noValidate
        onSubmit={(event) => void submit(event)}
        className="space-y-5"
        aria-busy={isSubmitting}
      >
        <section
          className="space-y-5 rounded-2xl border bg-secondary/50 p-5 sm:p-7"
          aria-labelledby="education-heading"
        >
          <h2 id="education-heading" className="flex items-center gap-3 text-xl font-bold">
            <BookOpen className="size-6 shrink-0 text-ring" aria-hidden="true" />
            Учебная информация
          </h2>
          <p className="text-muted-foreground">Эти данные попадут на титульный лист.</p>
          {editing ? (
            <fieldset disabled={isSubmitting} className="grid min-w-0 gap-5 sm:grid-cols-2">
              <legend className="sr-only">Данные студента</legend>
              {profileFields.map(([key, label]) => (
                <FormField
                  key={key}
                  label={label}
                  autoComplete={
                    key === 'first_name'
                      ? 'given-name'
                      : key === 'last_name'
                        ? 'family-name'
                        : key === 'middle_name'
                          ? 'additional-name'
                          : 'off'
                  }
                  {...form.register(key)}
                  error={errors[key]?.message}
                />
              ))}
            </fieldset>
          ) : (
            <dl className="space-y-2">
              <ProfileRow label="ФИО" value={fullName} />
              <ProfileRow label="Группа" value={profile.group_name} />
              <ProfileRow label="Факультет" value={profile.faculty} />
              <ProfileRow label="Кафедра" value={profile.department} />
            </dl>
          )}
        </section>
        <section
          className="space-y-4 rounded-2xl border bg-secondary/50 p-5 sm:p-7"
          aria-labelledby="extra-heading"
        >
          <h2 id="extra-heading" className="flex items-center gap-3 text-xl font-bold">
            <Mail className="size-6 shrink-0 text-ring" aria-hidden="true" />
            Дополнительная информация
          </h2>
          <dl className="grid gap-3 xl:grid-cols-2">
            <ProfileRow label="Email" value={session?.user.email ?? ''} />
            <ProfileRow label="Роль" value={role} />
          </dl>
        </section>
        {errors.root?.server && (
          <p role="alert" className="text-destructive">
            {errors.root.server.message}
          </p>
        )}
        {editing && (
          <div className="flex flex-wrap justify-end gap-3">
            <Button
              type="button"
              variant="outline"
              disabled={isSubmitting}
              onClick={() => {
                form.reset(profile);
                setEditing(false);
              }}
              className="min-h-12 rounded-xl"
            >
              Отменить
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting}
              className="min-h-12 rounded-xl border border-ring"
            >
              <Check aria-hidden="true" />
              {isSubmitting ? 'Сохраняем…' : 'Сохранить изменения'}
            </Button>
          </div>
        )}
        {saved && (
          <p role="status" className="text-right text-ring">
            Изменения сохранены
          </p>
        )}
      </form>
    </>
  );
}

function ProfileRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid min-w-0 gap-2 rounded-xl border bg-secondary px-5 py-3 sm:grid-cols-[140px_minmax(0,1fr)]">
      <dt className="font-semibold">{label}</dt>
      <dd className="min-w-0 break-words text-muted-foreground">{value || 'Не указано'}</dd>
    </div>
  );
}
