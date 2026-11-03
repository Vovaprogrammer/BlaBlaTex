import { http, HttpResponse } from 'msw/http';
import { currentAccount, emptyProfile, mockState, refreshGeneratedFiles, timestamp } from './data';
import type { Schemas } from './data';
import { failure, guard, invalid, readBody, validText } from './responses';

export const authHandlers = [
  http.get('/api/v1/health', () => HttpResponse.json<Schemas['HealthResponse']>({ status: 'ok' })),
  http.get('/api/v1/auth/me', ({ request }) => {
    const denied = guard(request);
    if (denied) return denied;
    const account = currentAccount()!;
    return HttpResponse.json<Schemas['MeResponse']>({
      user: account.user,
      profile: account.profile,
    });
  }),
  http.post('/api/v1/auth/logout', ({ request }) => {
    if (currentAccount() && request.headers.get('X-CSRF-Protection') !== '1')
      return failure(403, 'forbidden', 'Обновите страницу и попробуйте ещё раз');
    mockState.current.currentUserId = null;
    return new HttpResponse(null, { status: 204 });
  }),
  http.post('/api/v1/auth/login', async ({ request }) => {
    const body = await readBody(request);
    if (typeof body.email !== 'string' || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email))
      return invalid('email', 'Введите корректный email');
    if (!validText(body.password, 128) || body.password.length === 0)
      return invalid('password', 'Введите пароль');
    const account = [...mockState.current.accounts.values()].find(
      (item) =>
        item.user.email === String(body.email).toLowerCase() && item.password === body.password,
    );
    if (!account) return failure(401, 'unauthorized', 'Неверный email или пароль');
    mockState.current.currentUserId = account.user.id;
    return HttpResponse.json<Schemas['MeResponse']>({
      user: account.user,
      profile: account.profile,
    });
  }),
  http.post('/api/v1/auth/register', async ({ request }) => {
    const body = await readBody(request);
    if (typeof body.email !== 'string' || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email))
      return invalid('email', 'Введите корректный email');
    if (!validText(body.password, 128) || body.password.length < 8)
      return invalid('password', 'Пароль должен содержать от 8 до 128 символов');
    if (body.consent !== true)
      return invalid('consent', 'Подтвердите согласие на обработку данных', 'literal_error');
    const email = body.email.toLowerCase();
    if ([...mockState.current.accounts.values()].some((item) => item.user.email === email))
      return failure(409, 'already_exists', 'Пользователь с таким email уже есть');
    const id = crypto.randomUUID();
    const account = {
      user: { id, email, role: 'student' as const, created_at: timestamp },
      profile: emptyProfile(),
      password: body.password,
    };
    mockState.current.accounts.set(id, account);
    mockState.current.currentUserId = id;
    return HttpResponse.json<Schemas['MeResponse']>(
      { user: account.user, profile: account.profile },
      { status: 201 },
    );
  }),
  http.get(
    '/api/v1/profile',
    ({ request }) =>
      guard(request) ?? HttpResponse.json<Schemas['ProfileOut']>(currentAccount()!.profile),
  ),
  http.put('/api/v1/profile', async ({ request }) => {
    const denied = guard(request);
    if (denied) return denied;
    const body = await readBody(request);
    const keys = [
      'last_name',
      'first_name',
      'middle_name',
      'group_name',
      'faculty',
      'department',
    ] as const;
    const profile = emptyProfile();
    for (const key of keys) {
      if (!validText(body[key])) return invalid(key);
      profile[key] = body[key];
    }
    profile.updated_at = new Date().toISOString();
    currentAccount()!.profile = profile;
    refreshGeneratedFiles(currentAccount()!.user.id);
    return HttpResponse.json<Schemas['ProfileOut']>(profile);
  }),
];
