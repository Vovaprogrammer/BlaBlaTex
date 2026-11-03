import { render } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach } from 'vitest';
import { createQueryClient } from '@/app/query-client';
import { ThemeProvider } from '@/app/theme-provider';
import { AppRoutes } from '@/app/router';

const clients: ReturnType<typeof createQueryClient>[] = [];
afterEach(() => clients.splice(0).forEach((client) => client.clear()));

export function renderApp(path: string) {
  const client = createQueryClient(() => {});
  clients.push(client);
  const result = render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { ...result, client };
}
