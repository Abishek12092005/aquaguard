/**
 * Bundles a *.check.jsx entry with the same alias + JSX settings Vite uses, so
 * the smoke-checks render the real component code.
 *
 *   node tests/buildSmoke.mjs tests/renderSmoke.check.jsx .render-smoke.mjs
 */
import esbuild from 'esbuild'
import { argv } from 'node:process'

const [entry, outfile] = argv.slice(2)
if (!entry || !outfile) {
  console.error('usage: node tests/buildSmoke.mjs <entry.jsx> <outfile>')
  process.exit(1)
}

await esbuild.build({
  entryPoints: [entry],
  bundle: true,
  platform: 'node',
  format: 'esm',
  outfile,
  alias: {
    // Auth, the router and the API client are all stubbed so a page renders
    // without a browser history, a network, or axios's `form-data` dependency
    // (which cannot be bundled as ESM for Node). None of them is what a render
    // smoke-check is testing; the page's own structure is.
    '@/context/useAuth': './tests/stubs/useAuth.js',
    'react-router-dom': './tests/stubs/react-router-dom.jsx',
    '@/api': './tests/stubs/api.js',
    '@': './src',
  },
  loader: { '.jsx': 'jsx' },
  jsx: 'automatic',
  // `import.meta.env` is a Vite-provided global; without it any module that
  // reads a VITE_ variable throws before the component ever runs.
  define: {
    'import.meta.env': JSON.stringify({ MODE: 'test', DEV: false, PROD: false }),
  },
  // Left external so Node resolves the real React rather than bundling it.
  external: ['react', 'react-dom', 'react-dom/server', 'react/jsx-runtime'],
  logLevel: 'info',
})
