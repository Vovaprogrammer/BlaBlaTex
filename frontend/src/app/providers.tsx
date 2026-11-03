import { useState, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { Toaster } from 'sonner';
import { createQueryClient } from './query-client';
import { useTheme } from './theme-context';

export function AppProviders({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const { theme } = useTheme();
  const [client] = useState(() => createQueryClient(() => navigate('/login', { replace: true })));
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster
        theme={theme}
        position="bottom-right"
        closeButton
        toastOptions={{
          style: {
            background: 'var(--card)',
            color: 'var(--foreground)',
            borderColor: 'var(--border)',
          },
        }}
      />
    </QueryClientProvider>
  );
}
