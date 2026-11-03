import { z } from 'zod';
import type { components } from '@/api/schema';

const text = z
  .string()
  .max(200, 'Не больше 200 символов')
  .refine((value) => !value.includes('\0'), 'Недопустимый символ в тексте');
export const profileSchema = z.object({
  last_name: text,
  first_name: text,
  middle_name: text,
  group_name: text,
  faculty: text,
  department: text,
} satisfies Record<keyof components['schemas']['ProfileUpdate'], typeof text>);

export const profileFields = [
  ['last_name', 'Фамилия'],
  ['first_name', 'Имя'],
  ['middle_name', 'Отчество'],
  ['group_name', 'Группа'],
  ['faculty', 'Факультет'],
  ['department', 'Кафедра'],
] as const;
