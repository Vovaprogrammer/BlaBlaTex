import type { components } from './schema';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: components['schemas']['ErrorBody']['details'] = {},
  ) {
    super(message);
    this.name = 'ApiError';
  }

  static async fromResponse(response: Response): Promise<ApiError> {
    try {
      const body: unknown = await response.json();
      const error = isRecord(body) ? body.error : undefined;
      if (
        isRecord(error) &&
        typeof error.code === 'string' &&
        typeof error.message === 'string' &&
        error.message.trim()
      ) {
        return new ApiError(
          response.status,
          error.code,
          error.message,
          isRecord(error.details) ? error.details : {},
        );
      }
    } catch {
      /* Прокси может вернуть HTML или пустое тело вместо ошибки API. */
    }
    return new ApiError(
      response.status,
      'http_error',
      'Не удалось выполнить запрос. Попробуйте ещё раз.',
    );
  }
}
