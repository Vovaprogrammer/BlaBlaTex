import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';
import { expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { currentAccount } from '@/mocks/data';
import { server } from '@/test/server';
import { failure, invalid } from '@/mocks/responses';

function filledProfile() {
  Object.assign(currentAccount()!.profile, {
    last_name: 'Студентов',
    first_name: 'Иван',
    group_name: 'ДЕМО-1',
    faculty: 'Учебный факультет',
    department: 'Учебная кафедра',
  });
}

test('пустой профиль открывается для заполнения, email и роль доступны только для чтения', async () => {
  renderApp('/profile');
  expect(await screen.findByLabelText('Фамилия')).toHaveValue('');
  expect(screen.getByText('Эти данные попадут на титульный лист.')).toBeInTheDocument();
  expect(screen.getByText('student@example.com')).toBeInTheDocument();
  expect(screen.queryByRole('textbox', { name: 'Email' })).not.toBeInTheDocument();
});

test('изменения сохраняются, обновляют сессию и видны после нового открытия', async () => {
  const first = renderApp('/profile');
  await screen.findByLabelText('Фамилия');
  fireEvent.change(screen.getByLabelText('Фамилия'), { target: { value: 'Студентов' } });
  fireEvent.change(screen.getByLabelText('Имя'), { target: { value: 'Иван' } });
  fireEvent.change(screen.getByLabelText('Группа'), { target: { value: 'ДЕМО-2' } });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Изменения сохранены');
  expect(first.client.getQueryData(['session'])).toMatchObject({
    profile: { last_name: 'Студентов', group_name: 'ДЕМО-2' },
  });
  expect(screen.queryByLabelText('Фамилия')).not.toBeInTheDocument();
  first.unmount();
  renderApp('/profile');
  expect(await screen.findByRole('heading', { name: 'Студентов Иван' })).toBeInTheDocument();
  expect(screen.getByText('ДЕМО-2')).toBeInTheDocument();
});

test('отмена возвращает серверные значения и не отправляет PUT', async () => {
  filledProfile();
  const put = vi.fn(() => HttpResponse.json({}));
  server.use(http.put('/api/v1/profile', put));
  renderApp('/profile');
  await screen.findByRole('button', { name: 'Изменить профиль' });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Изменить профиль' }));
  fireEvent.change(screen.getByLabelText('Группа'), { target: { value: 'Не сохранять' } });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Отменить' }));
  expect(screen.getByText('ДЕМО-1')).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Изменить профиль' }));
  expect(screen.getByLabelText('Группа')).toHaveValue('ДЕМО-1');
  expect(put).not.toHaveBeenCalled();
});

test('поле длиннее 200 символов не отправляется', async () => {
  const put = vi.fn(() => HttpResponse.json({}));
  server.use(http.put('/api/v1/profile', put));
  renderApp('/profile');
  await screen.findByLabelText('Фамилия');
  fireEvent.change(screen.getByLabelText('Факультет'), { target: { value: 'а'.repeat(201) } });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() =>
    expect(screen.getByLabelText('Факультет')).toHaveAccessibleDescription(
      'Не больше 200 символов',
    ),
  );
  expect(put).not.toHaveBeenCalled();
});

test('серверная валидация профиля показывается возле поля', async () => {
  server.use(http.put('/api/v1/profile', () => invalid('group_name', 'Проверьте группу')));
  renderApp('/profile');
  await screen.findByLabelText('Группа');
  fireEvent.change(screen.getByLabelText('Группа'), { target: { value: 'ДЕМО-3' } });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() =>
    expect(screen.getByLabelText('Группа')).toHaveAccessibleDescription('Проверьте группу'),
  );
  expect(screen.getByLabelText('Группа')).toHaveValue('ДЕМО-3');
});

test('ошибка сохранения не теряет введённое и разрешает повтор', async () => {
  server.use(http.put('/api/v1/profile', () => failure(500, 'internal', 'Профиль не сохранён')));
  renderApp('/profile');
  await screen.findByLabelText('Кафедра');
  fireEvent.change(screen.getByLabelText('Кафедра'), { target: { value: 'Демо-кафедра' } });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Профиль не сохранён');
  expect(screen.getByLabelText('Кафедра')).toHaveValue('Демо-кафедра');
  server.resetHandlers();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Изменения сохранены');
  expect(screen.getByText('Демо-кафедра')).toBeInTheDocument();
});

test('пустые значения допустимы и отправляются всеми шестью полями', async () => {
  let payload: unknown;
  server.use(
    http.put('/api/v1/profile', async ({ request }) => {
      payload = await request.clone().json();
    }),
  );
  renderApp('/profile');
  await screen.findByLabelText('Фамилия');
  await userEvent.setup().click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  await screen.findByText('Изменения сохранены');
  expect(payload).toEqual({
    last_name: '',
    first_name: '',
    middle_name: '',
    group_name: '',
    faculty: '',
    department: '',
  });
});

test('ошибка загрузки профиля имеет повтор, ошибка не раскрывает пустую форму', async () => {
  server.use(
    http.get('/api/v1/profile', () => failure(500, 'internal', 'Не удалось прочитать профиль')),
  );
  renderApp('/profile');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Не удалось прочитать профиль');
  expect(screen.queryByLabelText('Фамилия')).not.toBeInTheDocument();
  server.resetHandlers();
  await userEvent.setup().click(within(alert).getByRole('button', { name: 'Повторить' }));
  expect(await screen.findByLabelText('Фамилия')).toBeInTheDocument();
});

test('во время сохранения нельзя отправить повторно или отменить', async () => {
  server.use(
    http.put('/api/v1/profile', async () => {
      await delay(150);
      return failure(500, 'internal', 'Повторите позже');
    }),
  );
  renderApp('/profile');
  await screen.findByLabelText('Фамилия');
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  expect(await screen.findByRole('button', { name: 'Сохраняем…' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Отменить' })).toBeDisabled();
  await screen.findByRole('alert');
});
