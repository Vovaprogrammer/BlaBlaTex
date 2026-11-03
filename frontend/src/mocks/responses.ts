import { HttpResponse } from 'msw/http';
import { isRecord } from '@/api/api-error';
import { currentAccount } from './data';
import type { Schemas } from './data';

export function failure(
  status: number,
  code: Schemas['ErrorCode'],
  message: string,
  details: Schemas['ErrorBody']['details'] = {},
): Response {
  return HttpResponse.json<Schemas['ErrorResponse']>(
    { error: { code, message, details } },
    { status },
  );
}
export function invalid(field: string, message = 'Проверьте значение поля', type = 'value_error') {
  return failure(422, 'validation_error', 'Проверьте введённые данные', {
    errors: [{ loc: ['body', ...field.split('.')], type, message }],
  });
}
export function guard(request: Request) {
  if (!currentAccount()) return failure(401, 'unauthorized', 'Нужно войти в аккаунт');
  if (
    !['GET', 'HEAD', 'OPTIONS'].includes(request.method) &&
    request.headers.get('X-CSRF-Protection') !== '1'
  )
    return failure(403, 'forbidden', 'Обновите страницу и попробуйте ещё раз');
}
export async function readBody(request: Request): Promise<Record<string, unknown>> {
  try {
    const value: unknown = await request.json();
    return isRecord(value) ? value : {};
  } catch {
    return {};
  }
}
export function validText(value: unknown, max = 200): value is string {
  return typeof value === 'string' && value.length <= max && !value.includes('\0');
}
export function validPath(path: string) {
  return (
    path.length > 0 &&
    path.length <= 255 &&
    !/[\\:]/.test(path) &&
    !Array.from(path).some((char) => char.charCodeAt(0) < 32) &&
    path.split('/')[0] !== 'out' &&
    path
      .split('/')
      .every(
        (part) =>
          part.length > 0 && part.length <= 100 && !part.startsWith('.') && part !== 'latexmkrc',
      )
  );
}
export function checkFields(value: unknown) {
  if (!isRecord(value)) return invalid('fields');
  const result: Schemas['ProjectOut']['fields'] = {};
  const fields = new Set(['report_title', 'lab_number', 'variant', 'comment']);
  for (const key of Object.keys(value))
    if (!fields.has(key))
      return invalid(`fields.${key}`, 'Такого поля нет в шаблоне', 'extra_forbidden');
  for (const field of ['report_title', 'lab_number', 'comment', 'variant'] as const) {
    const item =
      value[field] ??
      ({ lab_number: 1, comment: '', variant: 'А' } as Record<string, unknown>)[field];
    if (field === 'lab_number') {
      if (!Number.isSafeInteger(item))
        return invalid(`fields.${field}`, 'Ожидается целое число', 'int_type');
      result[field] = item as number;
    } else {
      if (!validText(item, field === 'comment' ? 10_000 : 200))
        return invalid(`fields.${field}`, 'Проверьте длину и тип значения');
      if (field === 'report_title' && !item.trim())
        return invalid(`fields.${field}`, 'Обязательное поле', 'missing');
      if (field === 'variant' && !['А', 'Б'].includes(item))
        return invalid(`fields.${field}`, 'Выберите вариант из списка');
      result[field] = item;
    }
  }
  return result;
}
