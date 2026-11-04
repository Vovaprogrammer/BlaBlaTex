import { z } from 'zod';
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
