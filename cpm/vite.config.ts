import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5180, strictPort: true,
    proxy: { '/cpm-api': 'http://127.0.0.1:5181' } },
  build: { outDir: 'dist', emptyOutDir: true },
});
