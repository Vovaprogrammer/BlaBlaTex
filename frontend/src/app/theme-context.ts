import { createContext, useContext } from 'react';

export type Theme = 'dark' | 'light';
export const themeContext = createContext<{ theme: Theme; toggleTheme: () => void } | null>(null);

export function useTheme() {
  const context = useContext(themeContext);
  if (!context) throw new Error('Переключатель темы должен находиться внутри ThemeProvider');
  return context;
}
