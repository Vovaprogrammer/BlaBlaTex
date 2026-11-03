import { Navigate, Route, Routes } from 'react-router';
import { lazy, Suspense } from 'react';
import { App } from './App';
import { ProjectsPage } from '@/features/projects/projects-page';
import { WorkspacePage } from '@/features/workspace/workspace-page';
import { SettingsPage } from '@/features/settings/settings-page';
import { PagePlaceholder } from '@/components/page-placeholder';
import { AuthLayout } from './auth-layout';
import { RequireAuth } from './require-auth';
import { Brand } from '@/components/brand';
import { Link } from 'react-router';

const AuthPage = lazy(() =>
  import('@/features/auth/auth-page').then((module) => ({ default: module.AuthPage })),
);
const ProfilePage = lazy(() =>
  import('@/features/profile/profile-page').then((module) => ({ default: module.ProfilePage })),
);

function LoadingPage({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<p role="status">Открываем страницу…</p>}>{children}</Suspense>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route index element={<Navigate to="/projects" replace />} />
      <Route element={<AuthLayout />}>
        <Route
          path="login"
          element={
            <LoadingPage>
              <AuthPage mode="login" />
            </LoadingPage>
          }
        />
        <Route
          path="register"
          element={
            <LoadingPage>
              <AuthPage mode="register" />
            </LoadingPage>
          }
        />
      </Route>
      <Route element={<RequireAuth />}>
        <Route element={<App />}>
          <Route
            path="profile"
            element={
              <LoadingPage>
                <ProfilePage />
              </LoadingPage>
            }
          />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/:id" element={<WorkspacePage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route
        path="*"
        element={
          <main className="mx-auto max-w-xl space-y-8 px-6 py-20">
            <Brand />
            <PagePlaceholder
              title="Страница не найдена"
              description="Вернитесь на главную, чтобы продолжить работу."
            />
            <Link to="/projects" className="text-ring underline">
              На главную
            </Link>
          </main>
        }
      />
    </Routes>
  );
}
