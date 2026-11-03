import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { AppRoutes } from './app/router';
import { ThemeProvider } from './app/theme-provider';
import { AppProviders } from './app/providers';
import { ErrorBoundary } from './app/error-boundary';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <ErrorBoundary>
        <BrowserRouter>
          <AppProviders>
            <AppRoutes />
          </AppProviders>
        </BrowserRouter>
      </ErrorBoundary>
    </ThemeProvider>
  </StrictMode>,
);
