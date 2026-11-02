import { Navigate, Route, Routes } from 'react-router';
import { App } from './App';
import { AuthPage } from '@/features/auth/auth-page';
import { ProfilePage } from '@/features/profile/profile-page';
import { ProjectsPage } from '@/features/projects/projects-page';
import { WorkspacePage } from '@/features/workspace/workspace-page';
import { SettingsPage } from '@/features/settings/settings-page';
import { PagePlaceholder } from '@/components/page-placeholder';

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<App />}>
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="login" element={<AuthPage mode="login" />} />
        <Route path="register" element={<AuthPage mode="register" />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:id" element={<WorkspacePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route
          path="*"
          element={
            <PagePlaceholder
              title="Страница не найдена"
              description="Выберите нужный раздел в меню выше."
            />
          }
        />
      </Route>
    </Routes>
  );
}
