import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { server } from './server';
import { resetMockState } from '@/mocks/data';
vi.mock('react-pdf', async () => ({
  ...(await import('./pdf-mock')),
  pdfjs: { GlobalWorkerOptions: { workerSrc: '' } },
}));
globalThis.IntersectionObserver = class implements IntersectionObserver {
  root = null;
  rootMargin = '';
  thresholds = [];
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
};

// Холодная загрузка lazy-модулей в тестовом раннере требует времени на преобразование.
configure({ asyncUtilTimeout: 5000 });

// jsdom не измеряет раскладку; изменение размеров проверяется отдельно в браузере.
globalThis.ResizeObserver = class implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Геометрию текста CodeMirror проверяем в Chrome, в jsdom измерения отсутствуют.
Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
Range.prototype.getBoundingClientRect = () => new DOMRect();

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockState();
});
afterAll(() => server.close());
