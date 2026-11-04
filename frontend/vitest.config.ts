import { mergeConfig, defineConfig } from 'vitest/config';
import viteConfig from './vite.config.ts';

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      maxWorkers: 4,
      testTimeout: 10_000,
      environmentOptions: { jsdom: { url: 'http://localhost:5173' } },
      setupFiles: ['./src/test/setup.ts'],
    },
  }),
);
