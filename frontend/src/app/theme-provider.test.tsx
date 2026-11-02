import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { ThemeProvider } from './theme-provider';
import { ThemeToggle } from '@/components/theme-toggle';

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = '';
});
afterEach(() => vi.restoreAllMocks());

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

test('тёмная тема включена по умолчанию, выбор сохраняется после повторного открытия', async () => {
  const user = userEvent.setup();
  const { unmount } = renderToggle();
  expect(document.documentElement).toHaveClass('dark');
  await user.click(screen.getByRole('button', { name: 'Включить светлую тему' }));
  expect(document.documentElement).not.toHaveClass('dark');
  expect(localStorage.getItem('bbt-theme')).toBe('light');
  unmount();
  renderToggle();
  expect(screen.getByRole('button', { name: 'Включить тёмную тему' })).toBeInTheDocument();
  expect(document.documentElement).not.toHaveClass('dark');
  await user.click(screen.getByRole('button', { name: 'Включить тёмную тему' }));
  expect(document.documentElement).toHaveClass('dark');
  expect(localStorage.getItem('bbt-theme')).toBe('dark');
});

test('неизвестное сохранённое значение не ломает тему', () => {
  localStorage.setItem('bbt-theme', 'unknown');
  renderToggle();
  expect(document.documentElement).toHaveClass('dark');
});

test('переключение работает, даже если браузер запретил чтение и запись настройки', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('Хранилище недоступно', 'SecurityError');
  });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('Хранилище недоступно', 'SecurityError');
  });
  renderToggle();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Включить светлую тему' }));
  expect(document.documentElement).not.toHaveClass('dark');
  expect(screen.getByRole('button', { name: 'Включить тёмную тему' })).toBeInTheDocument();
});
