import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

// Vitest 4 augments vite's UserConfig but bundles its own vite version,
// which causes a typecheck mismatch when vite versions differ. We attach
// the test block via Object.assign to keep `defineConfig` strict-typed
// while still being read by vitest at runtime.
const config = defineConfig({
  base: '/admin/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/admin/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p: string) => {
          const tok = process.env.VITE_ADMIN_TOKEN;
          if (!tok) return p;
          const sep = p.includes('?') ? '&' : '?';
          return `${p}${sep}token=${tok}`;
        },
      },
      '/mcp': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
});

// @ts-expect-error vitest config block — recognized at runtime.
config.test = {
  environment: 'jsdom',
  globals: true,
  setupFiles: ['./src/setupTests.ts'],
};

export default config;
