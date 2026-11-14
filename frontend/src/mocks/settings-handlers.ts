import { http, HttpResponse } from 'msw/http';
import { currentAccount, mockState, timestamp, type Schemas } from './data';
import { guard, invalid, readBody } from './responses';

const keyPath = '/api/v1/settings/llm-key';
const provider = 'openrouter';

export const settingsHandlers = [
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
