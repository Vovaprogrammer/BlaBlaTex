import { Moon, Sun } from 'lucide-react';
import { useTheme } from '@/app/theme-context';
import { Button } from '@/components/ui/button';

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const label = theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему';
  return <Button variant="outline" size="icon" onClick={toggleTheme} aria-label={label} title={label}>
    {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
  </Button>;
}
