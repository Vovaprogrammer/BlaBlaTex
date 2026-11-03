import { Navigate, Route, Routes } from 'react-router';
import { App } from './App';
import { AuthPage } from '@/features/auth/auth-page';
import { ProfilePage } from '@/features/profile/profile-page';
import { ProjectsPage } from '@/features/projects/projects-page';
import { WorkspacePage } from '@/features/workspace/workspace-page';
import { SettingsPage } from '@/features/settings/settings-page';
import { PagePlaceholder } from '@/components/page-placeholder';
import { AuthLayout } from './auth-layout';
import { RequireAuth } from './require-auth';
import { Brand } from '@/components/brand';
import { Link } from 'react-router';

export function AppRoutes() {
  return (
    <Routes>
      <Route index element={<Navigate to="/projects" replace />} />
      <Route element={<AuthLayout />}>
        <Route path="login" element={<AuthPage mode="login" />} />
        <Route path="register" element={<AuthPage mode="register" />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route element={<App />}>
          <Route path="profile" element={<ProfilePage />} />
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
