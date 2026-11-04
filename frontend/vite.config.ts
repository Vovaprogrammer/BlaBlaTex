import { defineConfig, normalizePath } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';
import { createRequire } from 'node:module';
import path from 'node:path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';

const require = createRequire(import.meta.url);
const pdfAssets = path.dirname(require.resolve('pdfjs-dist/package.json'));
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    viteStaticCopy({
      targets: ['cmaps', 'standard_fonts', 'wasm'].map((name) => ({
        src: normalizePath(path.join(pdfAssets, name)),
        dest: '',
      })),
    }),
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { port: 5173, strictPort: true, proxy: { '/api': 'http://localhost:8000' } },
});
