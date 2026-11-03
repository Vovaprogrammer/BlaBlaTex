import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';
import { expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { mockState, demoPassword } from '@/mocks/data';
import { failure, invalid } from '@/mocks/responses';

function fill(register = false, email = 'new-student@example.com', password = demoPassword) {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } });
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: password } });
  if (register) {
    fireEvent.change(screen.getByLabelText('Повторите пароль'), { target: { value: password } });
    fireEvent.click(screen.getByRole('checkbox'));
  }
}

test('невалидные email и короткий пароль не отправляются на сервер', async () => {
  const request = vi.fn(() => HttpResponse.json({}));
  server.use(http.post('/api/v1/auth/register', request));
  renderApp('/register');
  fill(true, 'не email', 'short');
  await userEvent.setup().click(screen.getByRole('button', { name: 'Зарегистрироваться' }));
  expect(await screen.findByText('Введите корректный email')).toBeInTheDocument();
  expect(screen.getByText('Пароль должен содержать минимум 8 символов')).toBeInTheDocument();
  expect(request).not.toHaveBeenCalled();
});

test('регистрация проверяет повтор пароля и явное согласие', async () => {
  renderApp('/register');
  fill(false);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Зарегистрироваться' }));
  expect(await screen.findByText('Пароли не совпадают')).toBeInTheDocument();
  expect(screen.getByText('Подтвердите согласие на обработку данных')).toBeInTheDocument();
});

test('регистрация отправляет только контрактные поля и открывает профиль', async () => {
  mockState.current.currentUserId = null;
  let payload: unknown;
  server.use(
    http.post('/api/v1/auth/register', async ({ request }) => {
      payload = await request.clone().json();
    }),
  );
  renderApp('/register');
  fill(true);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Зарегистрироваться' }));
  expect(await screen.findByRole('heading', { name: 'Профиль' })).toBeInTheDocument();
  expect(payload).toEqual({
    email: 'new-student@example.com',
    password: demoPassword,
    consent: true,
  });
});

test('повторный email показывается возле email, введённые данные сохраняются', async () => {
  renderApp('/register');
  fill(true, 'student@example.com');
  await userEvent.setup().click(screen.getByRole('button', { name: 'Зарегистрироваться' }));
  expect(await screen.findByLabelText('Email')).toHaveAccessibleDescription(
    'Пользователь с таким email уже есть',
  );
  expect(screen.getByLabelText('Пароль')).toHaveValue(demoPassword);
});

test('неверный пароль не очищает кэш и не сбрасывает форму входа', async () => {
  const { client } = renderApp('/login');
  client.setQueryData(['existing'], 'marker');
  fill(false, 'student@example.com', 'wrong-password');
  await userEvent.setup().click(screen.getByRole('button', { name: 'Войти' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Неверный email или пароль');
  expect(client.getQueryData(['existing'])).toBe('marker');
  expect(screen.getByLabelText('Email')).toHaveValue('student@example.com');
});

test('серверная ошибка 422 попадает в нужное поле', async () => {
  server.use(http.post('/api/v1/auth/login', () => invalid('email', 'Сервер отклонил этот email')));
  renderApp('/login');
  fill();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Войти' }));
  await waitFor(() =>
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription(
      'Сервер отклонил этот email',
    ),
  );
});

test('сбой сервера сохраняет введённые данные и разрешает повтор', async () => {
  server.use(http.post('/api/v1/auth/login', () => failure(500, 'internal', 'Попробуйте позже')));
  renderApp('/login');
  fill(false, 'student@example.com');
  await userEvent.setup().click(screen.getByRole('button', { name: 'Войти' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Попробуйте позже');
  expect(screen.getByLabelText('Email')).toHaveValue('student@example.com');
  server.resetHandlers();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Войти' }));
  expect(await screen.findByRole('heading', { name: 'Ваши проекты' })).toBeInTheDocument();
});

test('во время отправки поля и кнопка блокируются', async () => {
  server.use(
    http.post('/api/v1/auth/login', async () => {
      await delay(150);
      return failure(401, 'unauthorized', 'Неверный пароль');
    }),
  );
  renderApp('/login');
  fill();
  fireEvent.click(screen.getByRole('button', { name: 'Войти' }));
  expect(await screen.findByRole('button', { name: 'Подождите…' })).toBeDisabled();
  expect(screen.getByLabelText('Email')).toBeDisabled();
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: 'Войти' })).toBeEnabled();
});

test('переход на регистрацию не переносит пароль из формы входа', async () => {
  renderApp('/login');
  fill();
  await userEvent.setup().click(screen.getByRole('link', { name: 'Зарегистрироваться' }));
  expect(screen.getByLabelText('Пароль')).toHaveValue('');
});
