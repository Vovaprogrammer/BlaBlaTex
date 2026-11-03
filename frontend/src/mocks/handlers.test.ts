import { expect, test } from 'vitest';
import { api } from '@/api/client';
import { demoId, demoPassword } from './data';

const path = { pid: demoId, path: 'main.tex' };
const profile = {
  last_name: '',
  first_name: '',
  middle_name: '',
  group_name: '',
  faculty: '',
  department: '',
};

test.each(['login', 'register'])('мок %s проверяет CSRF при открытой сессии', async (action) => {
  const response = await fetch(`http://localhost:5173/api/v1/auth/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'student@example.com', password: demoPassword, consent: true }),
  });
  expect(response.status).toBe(403);
  expect((await api.GET('/api/v1/auth/me')).data?.user.id).toBe(demoId);
});

test('папка files внутри пути не обрезает имя файла', async () => {
  const params = { path: { pid: demoId, path: 'chapters/files/example.tex' } };
  await api.PUT('/api/v1/projects/{pid}/files/{path}', {
    params,
    body: 'Демонстрационный текст',
    headers: { 'Content-Type': 'text/plain', 'If-None-Match': '*' },
  });
  const result = await api.GET('/api/v1/projects/{pid}/files/{path}', { params, parseAs: 'text' });
  expect(result.data).toBe('Демонстрационный текст');
  const tree = await api.GET('/api/v1/projects/{pid}/tree', { params: { path: { pid: demoId } } });
  expect(tree.data?.items.some((item) => item.path === params.path.path)).toBe(true);
});

test('моки сессии не раскрывают пароль, выход и повторный вход работают', async () => {
  const me = await api.GET('/api/v1/auth/me');
  expect(Object.keys(me.data!)).toEqual(['user', 'profile']);
  expect(me.data?.user.email).toBe('student@example.com');
  await api.POST('/api/v1/auth/logout');
  await expect(api.GET('/api/v1/auth/me')).rejects.toMatchObject({ status: 401 });
  const login = await api.POST('/api/v1/auth/login', {
    body: { email: 'STUDENT@example.com', password: demoPassword },
  });
  expect(login.data?.user.id).toBe(demoId);
});

test('новый аккаунт получает пустой профиль и не видит чужие проекты', async () => {
  const registered = await api.POST('/api/v1/auth/register', {
    body: { email: 'new@example.com', password: demoPassword, consent: true },
  });
  expect(registered.response.status).toBe(201);
  expect(registered.data?.profile.first_name).toBe('');
  expect((await api.GET('/api/v1/projects')).data?.items).toEqual([]);
  await expect(
    api.GET('/api/v1/projects/{pid}', { params: { path: { pid: demoId } } }),
  ).rejects.toMatchObject({ status: 404 });
  await expect(
    api.POST('/api/v1/auth/register', {
      body: { email: 'NEW@example.com', password: demoPassword, consent: true },
    }),
  ).rejects.toMatchObject({ status: 409 });
});

test('создание, переименование и удаление проекта; ошибочная правка не меняет данные', async () => {
  const created = await api.POST('/api/v1/projects', {
    body: {
      title: 'Тестовый отчёт',
      template_slug: 'demo-lab',
      fields: { report_title: 'Учебная работа' },
    },
  });
  const params = { path: { pid: created.data!.id } };
  expect(created.response.status).toBe(201);
  expect(created.data?.fields.lab_number).toBe(1);
  await expect(
    api.PATCH('/api/v1/projects/{pid}', {
      params,
      body: { title: 'Не должно сохраниться', fields: { report_title: 'x'.repeat(201) } },
    }),
  ).rejects.toMatchObject({ status: 422 });
  expect((await api.GET('/api/v1/projects/{pid}', { params })).data?.title).toBe('Тестовый отчёт');
  await api.PATCH('/api/v1/projects/{pid}', { params, body: { title: 'Новое название' } });
  expect((await api.GET('/api/v1/projects/{pid}', { params })).data?.title).toBe('Новое название');
  expect((await api.DELETE('/api/v1/projects/{pid}', { params })).response.status).toBe(204);
  await expect(api.GET('/api/v1/projects/{pid}', { params })).rejects.toMatchObject({
    status: 404,
  });
});

test('сохранение файла проверяет версию и возвращает новый ETag при чтении', async () => {
  const result = await api.GET('/api/v1/projects/{pid}/files/{path}', {
    params: { path },
    parseAs: 'text',
  });
  const etag = result.response.headers.get('ETag');
  await api.PUT('/api/v1/projects/{pid}/files/{path}', {
    params: { path },
    body: 'Новый текст',
    headers: { 'Content-Type': 'text/plain', 'If-Match': etag },
  });
  const updated = await api.GET('/api/v1/projects/{pid}/files/{path}', {
    params: { path },
    parseAs: 'text',
  });
  expect(updated.data).toBe('Новый текст');
  expect(updated.response.headers.get('ETag')).not.toBe(etag);
  await expect(
    api.PUT('/api/v1/projects/{pid}/files/{path}', {
      params: { path },
      body: 'Устаревший текст',
      headers: { 'If-Match': etag },
    }),
  ).rejects.toMatchObject({ status: 412, details: { current_version: 2 } });
  await expect(
    api.PUT('/api/v1/projects/{pid}/files/{path}', {
      params: { path },
      body: '',
      headers: { 'If-None-Match': '*' },
    }),
  ).rejects.toMatchObject({ status: 409 });
});

test('сгенерированный файл защищён от записи, удаления и перемещения', async () => {
  const params = { path: { ...path, path: 'meta.tex' } };
  await expect(
    api.PUT('/api/v1/projects/{pid}/files/{path}', { params, body: '' }),
  ).rejects.toMatchObject({ status: 403 });
  await expect(api.DELETE('/api/v1/projects/{pid}/files/{path}', { params })).rejects.toMatchObject(
    { status: 403 },
  );
  await expect(
    api.POST('/api/v1/projects/{pid}/move', {
      params: { path: { pid: demoId } },
      body: { from: 'meta.tex', to: 'copy.tex' },
    }),
  ).rejects.toMatchObject({ status: 403 });
});

test('Unicode-пути, дерево, создание папки, перенос и удаление файла', async () => {
  const params = { path: { pid: demoId } };
  const fileParams = { path: { pid: demoId, path: 'разделы/цель.tex' } };
  await api.POST('/api/v1/projects/{pid}/folders', { params, body: { path: 'разделы' } });
  expect(
    (
      await api.PUT('/api/v1/projects/{pid}/files/{path}', {
        params: fileParams,
        body: 'Цель',
        headers: { 'Content-Type': 'text/plain', 'If-None-Match': '*' },
      })
    ).response.status,
  ).toBe(201);
  const moved = await api.POST('/api/v1/projects/{pid}/move', {
    params,
    body: { from: 'разделы/цель.tex', to: 'разделы/итог.tex' },
  });
  expect(moved.data?.path).toBe('разделы/итог.tex');
  const tree = await api.GET('/api/v1/projects/{pid}/tree', { params });
  expect(tree.data?.items.map((item) => item.path)).toContain('разделы/итог.tex');
  await api.DELETE('/api/v1/projects/{pid}/files/{path}', {
    params: { path: { ...fileParams.path, path: 'разделы/итог.tex' } },
  });
  await expect(
    api.GET('/api/v1/projects/{pid}/files/{path}', {
      params: { path: { ...fileParams.path, path: '../secret.tex' } },
      parseAs: 'text',
    }),
  ).rejects.toMatchObject({ status: 422 });
});

test('изменение профиля обновляет версию автоматически создаваемого файла', async () => {
  const params = { path: { ...path, path: 'meta.tex' } };
  const before = await api.GET('/api/v1/projects/{pid}/files/{path}', { params, parseAs: 'text' });
  const updated = await api.PUT('/api/v1/profile', {
    body: { ...profile, group_name: 'Демо-группа' },
  });
  expect(updated.data?.group_name).toBe('Демо-группа');
  const after = await api.GET('/api/v1/projects/{pid}/files/{path}', { params, parseAs: 'text' });
  expect(after.response.headers.get('ETag')).not.toBe(before.response.headers.get('ETag'));
});

test('сборка отдаёт только заранее заданную PDF-фикстуру и честный демонстрационный лог', async () => {
  const build = await api.POST('/api/v1/projects/{pid}/builds', {
    params: { path: { pid: demoId } },
  });
  expect(build.response.status).toBe(201);
  const params = { path: { bid: build.data!.id } };
  expect((await api.GET('/api/v1/builds/{bid}', { params })).data?.has_pdf).toBe(true);
  const pdf = await api.GET('/api/v1/builds/{bid}/pdf', { params, parseAs: 'arrayBuffer' });
  expect(new TextDecoder().decode(pdf.data).startsWith('%PDF-1.4')).toBe(true);
  const log = await api.GET('/api/v1/builds/{bid}/log', { params, parseAs: 'text' });
  expect(log.data).toContain('Реальная компиляция не выполнялась');
  const latest = await api.GET('/api/v1/projects/{pid}/builds/latest', {
    params: { path: { pid: demoId } },
  });
  expect(latest.data?.id).toBe(build.data?.id);
});

test('список шаблонов не раскрывает детали, а неизвестный адрес API не уходит в сеть', async () => {
  const list = await api.GET('/api/v1/templates');
  expect(Object.keys(list.data!.items[0]!)).not.toContain('fields');
  expect(
    (
      await api.GET('/api/v1/templates/{slug}', { params: { path: { slug: 'demo-lab' } } })
    ).data?.fields.map((field) => field.type),
  ).toEqual(['string', 'int', 'text', 'select']);
  const response = await fetch('http://localhost:5173/api/v1/unknown');
  expect(response.status).toBe(404);
});
