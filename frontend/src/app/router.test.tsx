import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { expect, test } from 'vitest';
import { AppRoutes } from './router';
import { ThemeProvider } from './theme-provider';

function openPage(path: string) {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

test.each([
  ['/', 'Ваши проекты'],
  ['/projects', 'Ваши проекты'],
  ['/login', 'Вход'],
  ['/register', 'Регистрация'],
  ['/profile', 'Профиль'],
  ['/settings', 'Настройки'],
  ['/projects/00000000-0000-4000-8000-000000000001', 'Рабочее окно'],
  ['/unknown', 'Страница не найдена'],
])('прямая ссылка %s открывает нужную страницу', (path, heading) => {
  openPage(path);
  expect(screen.getByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
});

test('переход между страницами сохраняет выбранную тему и выделяет раздел', async () => {
  openPage('/projects');
  const user = userEvent.setup();
  const toggle = screen.getByRole('button', { name: /Включить .+ тему/ });
  const previousTheme = document.documentElement.classList.contains('dark');
  await user.click(toggle);
  await user.click(screen.getByRole('link', { name: 'Регистрация' }));
  expect(screen.getByRole('heading', { name: 'Регистрация' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Регистрация' })).toHaveAttribute('aria-current', 'page');
  expect(document.documentElement.classList.contains('dark')).toBe(!previousTheme);
});
