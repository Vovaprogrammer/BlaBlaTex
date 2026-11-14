import { z } from 'zod';
import { ApiError, isRecord } from '@/api/api-error';
import type { components } from '@/api/schema';

type Field = components['schemas']['TemplateField'];
export const projectTitle = z
  .string()
  .trim()
  .min(1, 'Введите название проекта')
  .max(200, 'Не больше 200 символов')
  .refine((value) => !value.includes('\0'), 'Недопустимый символ');
export function createProjectSchema(fields: Field[]) {
  return z
    .object({ title: projectTitle, fields: z.record(z.string(), z.string()) })
    .superRefine((input, context) => {
      validateTemplateFields(fields, input, context);
    });
}
export type ProjectForm = z.infer<ReturnType<typeof createProjectSchema>>;
export function projectFields(
  fields: Field[],
  input: ProjectForm['fields'],
): components['schemas']['ProjectCreate']['fields'] {
  const result: components['schemas']['ProjectCreate']['fields'] = {};
  for (const field of fields) {
    const value = input[field.key] ?? '';
    if (field.type === 'select' && !value) continue;
    if (field.type === 'int') {
      if (value.trim()) result[field.key] = Number(value);
    } else result[field.key] = value;
  }
  return result;
}

export type TemplateFieldsForm = { fields: Record<string, string> };
type TemplateFieldPath = `fields.${string}`;

function validateTemplateFields(
  fields: Field[],
  input: TemplateFieldsForm,
  context: z.RefinementCtx,
) {
  for (const field of fields) {
    const value = input.fields[field.key] ?? '';
    let message: string | undefined;
    if (field.required && !value.trim()) message = 'Обязательное поле';
    else if (
      field.type === 'int' &&
      value.trim() &&
      (!/^-?\d+$/.test(value.trim()) || !Number.isSafeInteger(Number(value)))
    )
      message = 'Введите целое число';
    else if (value.length > (field.type === 'text' ? 10_000 : 200))
      message = `Не больше ${field.type === 'text' ? '10 000' : '200'} символов`;
    else if (field.type === 'select' && value && !field.options.includes(value))
      message = 'Выберите вариант из списка';
    else if (value.includes('\0')) message = 'Недопустимый символ';
    if (message) context.addIssue({ code: 'custom', path: ['fields', field.key], message });
  }
}

export function templateFieldsSchema(fields: Field[]) {
  return z
    .object({ fields: z.record(z.string(), z.string()) })
    .superRefine((input, context) => validateTemplateFields(fields, input, context));
}

export function defaultTemplateFields(
  fields: Field[],
  initial?: components['schemas']['ProjectOut']['fields'],
) {
  return Object.fromEntries(
    fields.map((field) => {
      const candidate = initial?.[field.key];
      const compatible =
        field.type === 'int'
          ? typeof candidate === 'number' && Number.isSafeInteger(candidate)
          : typeof candidate === 'string' &&
            (field.type === 'select'
              ? field.options.includes(candidate)
              : candidate.length <= (field.type === 'text' ? 10_000 : 200));
      return [field.key, String(compatible ? candidate : (field.default ?? ''))];
    }),
  );
}

export function applyTemplateFormErrors(
  error: unknown,
  fields: Field[],
  apply: (name: TemplateFieldPath | 'title', message: string, focus: boolean) => void,
) {
  let applied = false;
  if (error instanceof ApiError && Array.isArray(error.details.errors))
    for (const issue of error.details.errors) {
      if (
        !isRecord(issue) ||
        !Array.isArray(issue.loc) ||
        typeof issue.message !== 'string' ||
        issue.loc[0] !== 'body'
      )
        continue;
      const loc = issue.loc;
      const field =
        loc[1] === 'fields' && fields.some((field) => field.key === loc[2])
          ? (`fields.${String(issue.loc[2])}` as const)
          : issue.loc[1] === 'title'
            ? 'title'
            : undefined;
      if (field) {
        apply(field, issue.message, !applied);
        applied = true;
      }
    }
  return applied;
}
