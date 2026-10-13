/**
 * Minimal `react-router-dom` stub for the render smoke-checks.
 *
 * The pages under test only use `Link` (to build an href) and nothing else from
 * the router. Pulling in the real package would drag in a browser history and a
 * UMD bundle that Node cannot `require`, which is a lot of machinery to answer
 * "does this page render". So `Link` renders a plain anchor with the same href.
 *
 * The react-refresh rule is disabled for this file: it is a test double, never
 * hot-reloaded, and it must export the router's hooks alongside the components
 * to stand in for the real module.
 */
/* eslint-disable react-refresh/only-export-components */
import { createElement } from 'react'

export function Link({ to, children, ...rest }) {
  return createElement('a', { href: to, ...rest }, children)
}

export function NavLink({ to, children, ...rest }) {
  // NavLink's className may be a function of active state; the stub is never
  // active, so it is called with `{ isActive: false }`.
  const className = typeof rest.className === 'function' ? rest.className({ isActive: false }) : rest.className
  return createElement('a', { href: to, className }, children)
}

export function useLocation() {
  return { pathname: '/', state: null }
}

export function useNavigate() {
  return () => { }
}
