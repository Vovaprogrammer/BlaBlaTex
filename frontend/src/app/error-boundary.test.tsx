import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ErrorBoundary } from './error-boundary';

test('ошибка отрисовки заменяет пустой экран понятным сообщением', () => {
  const errorLog = vi.spyOn(console, 'error').mockImplementation(() => {});
  function Broken(): never {
    throw new Error('private implementation details');
  }
  try {
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Не удалось открыть страницу');
    expect(screen.getByRole('button', { name: 'Перезагрузить' })).toBeInTheDocument();
    expect(screen.queryByText('private implementation details')).not.toBeInTheDocument();
  } finally {
    errorLog.mockRestore();
  }
});
