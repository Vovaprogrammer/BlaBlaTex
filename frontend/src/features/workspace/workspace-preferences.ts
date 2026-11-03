import type { Layout } from 'react-resizable-panels';
import { isRecord } from '@/api/api-error';

const storageKey = 'bbt-workspace-panels';
const defaultLayout: Layout = { files: 20, chat: 44, document: 36 };

export function readPanelLayout(): Layout {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) ?? 'null');
    if (isRecord(saved)) {
      const values = ['files', 'chat', 'document'].map((key) => saved[key]);
      if (
        values.every(
          (value) =>
            typeof value === 'number' && Number.isFinite(value) && value >= 10 && value <= 70,
        ) &&
        Math.abs(
          (saved.files as number) + (saved.chat as number) + (saved.document as number) - 100,
        ) < 1
      )
        return {
          files: saved.files as number,
          chat: saved.chat as number,
          document: saved.document as number,
        };
    }
  } catch {
    /* Размеры необязательны, если хранилище недоступно. */
  }
  return defaultLayout;
}

export function savePanelLayout(layout: Layout) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(layout));
  } catch {
    /* Изменение размера продолжает работать без сохранения. */
  }
}
