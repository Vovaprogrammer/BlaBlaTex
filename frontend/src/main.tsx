import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { AppRoutes } from './app/router';
import { ThemeProvider } from './app/theme-provider';
import { AppProviders } from './app/providers';
import { ErrorBoundary } from './app/error-boundary';
import { startMocks } from './app/start-mocks';
import './index.css';

const root = createRoot(document.getElementById('root')!);
void startMocks()
  .then(() =>
    root.render(
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
    ),
  )
  .catch(() => {
    root.render(
      <main role="alert" className="p-8">
        Не удалось запустить приложение. Обновите страницу и попробуйте ещё раз.
      </main>,
    );
  });
