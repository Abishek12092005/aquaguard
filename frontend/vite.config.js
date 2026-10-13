import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import path from 'node:path'

// `__dirname` does not exist in an ES module (this file is type:module), so it is
// derived from the module URL. Vite happened to inject a shim, which is why this
// worked before - relying on that is fragile and fails under plain Node tooling.
const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  resolve: {
    alias: {
      // Import from anywhere as `@/api/client` instead of '../../../api/client'.
      '@': path.resolve(__dirname, './src'),

      // jsPDF's OPTIONAL integrations. It imports `canvg`, `dompurify` and
      // `html2canvas` lazily for the svg()/html()/addHtml() methods, none of
      // which this app calls. They are not installed, and without an alias the
      // dev server refuses to transform jsPDF at all ("Failed to resolve import
      // canvg"). Pointing them at a no-op stub makes the import resolve in dev
      // AND in the production build from one place, rather than relying on a
      // bundler-specific `external` flag. See the stub for the full reasoning.
      canvg: path.resolve(__dirname, './src/utils/jspdf-optional-stub.js'),
      dompurify: path.resolve(__dirname, './src/utils/jspdf-optional-stub.js'),
      html2canvas: path.resolve(__dirname, './src/utils/jspdf-optional-stub.js'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // Proxy API calls during development so the browser sees a single origin
    // and CORS never masks a real failure.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  // `vite preview` serves the PRODUCTION build, and without this it had no
  // proxy at all — so the app booted and then every API call went to the
  // built-in placeholder host. That makes the built bundle untestable in a
  // browser, which is exactly when it is most worth testing: the dev server is
  // 60s-per-load on a cold transform, while preview serves prebuilt assets
  // instantly. Mirrors `server.proxy` deliberately — the two must agree, or a
  // bug appears only in the mode nobody runs.
  preview: {
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // Sourcemaps are for DEBUGGING, not for shipping. Always emitting them added
    // 5.5MB — 44% of the whole bundle — which a production visitor never reads
    // and never asked for. Worse, it made every page load on this machine take
    // long enough to outlast the animation being tested. Development keeps them
    // (that is their purpose); production drops them.
    sourcemap: mode === 'development',
    rollupOptions: {
      output: {
        // Split heavy libraries so the initial dashboard bundle stays small.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
          http: ['axios'],
        },
      },
    },
  },
}))
