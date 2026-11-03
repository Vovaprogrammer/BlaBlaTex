import { z } from 'zod';

export function authSchema(register: boolean) {
  return z
    .object({
      email: z.string().trim().pipe(z.email('Введите корректный email')),
      password: z
        .string()
        .min(
          register ? 8 : 1,
          register ? 'Пароль должен содержать минимум 8 символов' : 'Введите пароль',
        )
        .max(128, 'Пароль должен быть не длиннее 128 символов'),
      confirmPassword: z.string(),
      consent: z.boolean(),
    })
    .superRefine((value, ctx) => {
      if (!register) return;
      if (value.password !== value.confirmPassword)
        ctx.addIssue({ code: 'custom', path: ['confirmPassword'], message: 'Пароли не совпадают' });
      if (!value.consent)
        ctx.addIssue({
          code: 'custom',
          path: ['consent'],
          message: 'Подтвердите согласие на обработку данных',
        });
    });
}
export type AuthValues = z.infer<ReturnType<typeof authSchema>>;
