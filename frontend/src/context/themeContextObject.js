import { createContext } from 'react'

/**
 * Theme context object.
 *
 * Kept in its own module so the provider file exports only a component — a file
 * exporting both a component and a plain value cannot be hot-reloaded by React
 * Fast Refresh. Same arrangement as `authContextObject` and
 * `aquaAIContextObject`.
 */
const ThemeContext = createContext(null)

export default ThemeContext
