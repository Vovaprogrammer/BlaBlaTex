import type { FieldPath, FieldValues, UseFormSetError } from 'react-hook-form';
import { ApiError, isRecord } from '@/api/api-error';
import { errorMessage } from '@/app/query-client';

export function showFormError<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly FieldPath<T>[],
) {
  let applied = false;
  if (error instanceof ApiError && Array.isArray(error.details.errors)) {
    for (const issue of error.details.errors) {
      if (!isRecord(issue) || !Array.isArray(issue.loc) || typeof issue.message !== 'string')
        continue;
      const loc = issue.loc;
      const field = fields.find((name) => loc[0] === 'body' && loc[1] === name);
      if (field) {
        setError(field, { type: 'server', message: issue.message }, { shouldFocus: !applied });
        applied = true;
      }
    }
  }
  if (!applied) setError('root.server', { message: errorMessage(error) });
}
