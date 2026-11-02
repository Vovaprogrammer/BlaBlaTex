import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './app/App';
import { ThemeProvider } from './app/theme-provider';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><ThemeProvider><App /></ThemeProvider></StrictMode>,
);
