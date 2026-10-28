import { defineConfig } from 'vite';

export default defineConfig({
  esbuild: { jsx: 'automatic' },
  server: { proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } } },
});