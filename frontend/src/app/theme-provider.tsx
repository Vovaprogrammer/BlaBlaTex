import { useEffect, useState, type ReactNode } from 'react';
import { themeContext, type Theme } from './theme-context';

function initialTheme(): Theme {
  try {
    return localStorage.getItem('bbt-theme') === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', theme === 'dark' ? '#141316' : '#f5f4f8');
  }, [theme]);
  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try {
      localStorage.setItem('bbt-theme', next);
    } catch {
      /* Настройка действует до закрытия страницы, если хранилище недоступно. */
    }
  }
  return <themeContext.Provider value={{ theme, toggleTheme }}>{children}</themeContext.Provider>;
}
