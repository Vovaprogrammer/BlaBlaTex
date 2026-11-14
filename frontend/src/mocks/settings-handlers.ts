import { http, HttpResponse } from 'msw/http';
import { currentAccount, mockState, timestamp, type Schemas } from './data';
import { failure, guard, invalid, readBody } from './responses';

const keyPath = '/api/v1/settings/llm-key';
const provider = 'openrouter';
const tokenPath = '/api/v1/tokens';
const tokenStates = new WeakMap<typeof mockState.current, Map<string, Schemas['ApiTokenList']>>();

function tokensFor(owner: string) {
  let accounts = tokenStates.get(mockState.current);
  if (!accounts) tokenStates.set(mockState.current, (accounts = new Map()));
  let list = accounts.get(owner);
  if (!list) accounts.set(owner, (list = { items: [] }));
  return list;
}

export const settingsHandlers = [
  http.get(tokenPath, ({ request }) => {
    const rejected = guard(request);
    if (rejected) return rejected;
    return HttpResponse.json(tokensFor(currentAccount()!.user.id));
  }),
  http.post(tokenPath, async ({ request }) => {
    const rejected = guard(request);
    if (rejected) return rejected;
    const list = tokensFor(currentAccount()!.user.id);
    const body = await readBody(request);
    if (body instanceof Response) return body;
    const name = typeof body.name === 'string' ? body.name.trim() : '';
    if (body.name != null && (!name || Array.from(name).length > 100))
      return invalid('name', 'Введите от 1 до 100 символов');
    if (list.items.length >= 20) return failure(403, 'forbidden', 'Достигнут лимит личных токенов');
    const item: Schemas['ApiTokenOut'] = {
      id: crypto.randomUUID(),
      name: name || 'Тестовый токен',
      created_at: new Date().toISOString(),
      last_used_at: null,
    };
    list.items.unshift(item);
    return HttpResponse.json<Schemas['ApiTokenCreated']>(
      { ...item, token: `demo_only_${item.id}` },
      { status: 201 },
    );
  }),
  http.delete(`${tokenPath}/:tid`, ({ request, params }) => {
    const rejected = guard(request);
    if (rejected) return rejected;
    const list = tokensFor(currentAccount()!.user.id);
    if (!list.items.some((item) => item.id === params.tid))
      return failure(404, 'not_found', 'Токен не найден');
    list.items = list.items.filter((item) => item.id !== params.tid);
    return new HttpResponse(null, { status: 204 });
  }),
  http.get('/api/v1/usage', ({ request }) => {
    const rejected = guard(request);
    if (rejected) return rejected;
    return HttpResponse.json<Schemas['UsageOut']>({
      tokens_used: 0,
      tokens_limit: 100_000,
      resets_at: timestamp,
      own_key: mockState.current.llmKeys.has(currentAccount()!.user.id),
    });
  }),
  http.get(keyPath, ({ request }) => {
    const rejected = guard(request);
    if (rejected) return rejected;
    return HttpResponse.json<Schemas['LlmKeySettings']>({
      provider,
      key: mockState.current.llmKeys.get(currentAccount()!.user.id) ?? null,
    });
  }),
  http.put(keyPath, async ({ request }) => {
    const rejected = guard(request);
    if (rejected) return rejected;
    const account = currentAccount()!;
    const body = await readBody(request);
    if (body instanceof Response) return body;
    const key = typeof body.key === 'string' ? body.key.trim() : '';
    if (!/^[!-~]{8,500}$/.test(key)) return invalid('key', 'Некорректный ключ');
    const data = { provider, last4: key.slice(-4), created_at: timestamp };
    mockState.current.llmKeys.set(account.user.id, data);
    return HttpResponse.json<Schemas['LlmKeyOut']>(data);
  }),
  http.delete(keyPath, ({ request }) => {
    const rejected = guard(request);
    if (rejected) return rejected;
    mockState.current.llmKeys.delete(currentAccount()!.user.id);
    return new HttpResponse(null, { status: 204 });
  }),
];
