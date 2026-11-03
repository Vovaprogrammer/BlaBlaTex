import { UserRound } from 'lucide-react';
import { Link } from 'react-router';

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const register = mode === 'register';
  return (
    <div className="flex min-h-96 flex-col justify-between gap-12">
      <div>
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
        <p className="mt-12 leading-relaxed text-muted-foreground">
          {register
            ? 'Создайте аккаунт, чтобы сохранять проекты и работать над отчётами по шаблону своей дисциплины.'
            : 'Войдите, чтобы открыть свои проекты и продолжить работу над отчётом.'}
        </p>
      </div>
      <p className="text-center text-sm">
        {register ? 'Уже есть аккаунт?' : 'Нет аккаунта?'}{' '}
        <Link
          to={register ? '/login' : '/register'}
          className="rounded text-ring underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
        >
          {register ? 'Войти' : 'Зарегистрироваться'}
        </Link>
      </p>
    </div>
  );
}
