import { defineConfig } from 'vite'
import path from 'path'
import react from '@vitejs/plugin-react'

// Test-only build config: bundles JUST the PDF generator so it can be driven
// from a headless browser without the backend running.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      canvg: path.resolve(__dirname, './src/utils/jspdf-optional-stub.js'),
      dompurify: path.resolve(__dirname, './src/utils/jspdf-optional-stub.js'),
      html2canvas: path.resolve(__dirname, './src/utils/jspdf-optional-stub.js'),
    },
  },
  build: {
    outDir: 'dist-qa',
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'qa-pdf-entry.js'),
      output: { format: 'es', entryFileNames: 'qa-pdf-entry.js' },
    },
  },
})
