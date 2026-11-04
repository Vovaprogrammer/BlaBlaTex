import { createContext, useContext } from 'react';

export type EditorTarget = { path: string; line: number; sequence: number };
export type OpenFileAtLine = (path: string, line?: number) => void;
export const EditorNavigationContext = createContext<OpenFileAtLine | null>(null);

/** Открывает исходник в правой панели; строка отсчитывается от единицы. */
export function useOpenFileAtLine(): OpenFileAtLine {
  const open = useContext(EditorNavigationContext);
  if (!open) throw new Error('Переход к исходнику доступен только внутри рабочего окна');
  return open;
}
