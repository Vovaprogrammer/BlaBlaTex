import { useId, type ComponentProps } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

export function FormField({
  label,
  error,
  hint,
  icon: Icon,
  pale = false,
  className,
  ...input
}: ComponentProps<'input'> & {
  label: string;
  error?: string;
  hint?: string;
  icon?: LucideIcon;
  pale?: boolean;
}) {
  const id = useId();
  const description =
    [input['aria-describedby'], hint ? `${id}-hint` : undefined, error ? `${id}-error` : undefined]
      .filter(Boolean)
      .join(' ') || undefined;
  return (
    <div className="min-w-0 space-y-2">
      <label htmlFor={id} className="block text-base font-medium">
        {label}
      </label>
      {hint && (
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      <div className="relative">
        {Icon && (
          <Icon
            aria-hidden="true"
            className={cn(
              'pointer-events-none absolute left-5 top-1/2 size-5 -translate-y-1/2',
              pale ? 'text-[#7b64c0]' : 'text-ring',
            )}
          />
        )}
        <input
          {...input}
          id={id}
          aria-invalid={Boolean(error)}
          aria-describedby={description}
          className={cn(
            'min-h-12 w-full min-w-0 rounded-xl border px-4 py-3 outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 aria-invalid:border-destructive',
            pale
              ? 'rounded-full border-transparent bg-[#d5d5dd] text-[#282333] placeholder:text-[#7b64c0] [color-scheme:light]'
              : 'bg-secondary text-foreground',
            Icon && 'pl-14',
            className,
          )}
        />
      </div>
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
