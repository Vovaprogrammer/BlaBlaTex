import { useId } from 'react';
import type { FieldErrors, UseFormRegisterReturn } from 'react-hook-form';
import type { components } from '@/api/schema';
import { templateFieldHint } from './project-field-hints';
import type { TemplateFieldsForm } from './project-form';

export function TemplateFields({
  fields,
  register,
  errors,
  disabled,
}: {
  fields: components['schemas']['TemplateField'][];
  register: (name: `fields.${string}`) => UseFormRegisterReturn;
  errors?: FieldErrors<TemplateFieldsForm>['fields'];
  disabled: boolean;
}) {
  const prefix = useId();
  return (
    <>
      {fields.map((field) => {
        const id = `${prefix}-${field.key}`;
        const error = errors?.[field.key]?.message;
        const registration = register(`fields.${field.key}`);
        const shared = {
          ...registration,
          id,
          disabled,
          'aria-invalid': Boolean(error),
          'aria-describedby': `${id}-hint${error ? ` ${id}-error` : ''}`,
          className:
            'min-h-12 w-full min-w-0 rounded-xl border bg-secondary p-3 outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive',
        };
        return (
          <div key={field.key} className="space-y-2">
            <label htmlFor={id} className="block font-medium">
              {field.label}
              {field.required && ' *'}
            </label>
            <p id={`${id}-hint`} className="text-sm text-muted-foreground">
              {templateFieldHint(field)}
            </p>
            {field.type === 'select' ? (
              <select {...shared}>
                <option value="">Выберите вариант</option>
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            ) : field.type === 'text' ? (
              <textarea {...shared} rows={4} maxLength={10000} />
            ) : (
              <input
                {...shared}
                type="text"
                inputMode={field.type === 'int' ? 'numeric' : 'text'}
                maxLength={field.type === 'int' ? 100 : 200}
              />
            )}
            {error && (
              <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
        );
      })}
    </>
  );
}
