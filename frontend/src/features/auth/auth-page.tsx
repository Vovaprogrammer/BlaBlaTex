import { PagePlaceholder } from '@/components/page-placeholder';

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  return (
    <PagePlaceholder
      title={mode === 'login' ? 'Вход' : 'Регистрация'}
      description="Войдите в аккаунт, чтобы работать над своими отчётами."
    />
  );
}
