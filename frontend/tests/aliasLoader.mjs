/**
 * Alias + JSX loader for Node's test runner.
 *
 * The project imports through the Vite alias `@/...` and uses JSX in the context
 * provider. Plain Node understands neither, so this loader:
 *
 *   1. rewrites `@/x` to the absolute path of `src/x`;
 *   2. transforms JSX/JSX-in-.jsx via esbuild, which Vite already ships with.
 *
 * It exists so the suggestion tests import the REAL modules rather than a copy
 * of their content — a test that re-declares the values it is checking proves
 * nothing.
 */

import { existsSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, resolve as resolvePath } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const SRC = resolvePath(here, '..', 'src')

/** Map `@/foo` to a real file under src/, trying the usual extensions. */
function resolveAlias(specifier) {
  if (!specifier.startsWith('@/')) return null
  const base = resolvePath(SRC, specifier.slice(2))
  const candidates = [
    base,
    `${base}.js`,
    `${base}.jsx`,
    `${base}.mjs`,
    resolvePath(base, 'index.js'),
    resolvePath(base, 'index.jsx'),
  ]
  return candidates.find((candidate) => existsSync(candidate)) || null
}

export async function resolve(specifier, context, nextResolve) {
  const resolved = resolveAlias(specifier)
  if (resolved) {
    return { url: pathToFileURL(resolved).href, shortCircuit: true }
  }
  return nextResolve(specifier, context)
}

export async function load(url, context, nextLoad) {
  // Transform JSX (and .js files reached through the alias that contain JSX).
  if (url.endsWith('.jsx') || url.endsWith('.js')) {
    const { readFile } = await import('node:fs/promises')
    const source = await readFile(fileURLToPath(url), 'utf8')
    if (source.includes('<') && /\.jsx$/.test(url)) {
      const esbuild = await import('esbuild')
      const { code } = await esbuild.transform(source, {
        loader: 'jsx',
        format: 'esm',
        jsx: 'automatic',
        sourcefile: url,
      })
      return { format: 'module', source: code, shortCircuit: true }
    }
  }
  return nextLoad(url, context)
}
