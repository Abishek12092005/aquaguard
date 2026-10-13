import { useCallback, useEffect, useMemo, useState } from 'react'

import ThemeContext from '@/context/themeContextObject'
import { STORAGE_KEYS } from '@/utils/constants'

/**
 * Light/dark theme provider.
 *
 * The theme is applied by putting (or removing) a `dark` class on <html>. Every
 * dark rule in this app is a `dark:` Tailwind variant keyed off that class, so
 * there is exactly one switch to flip and no per-component theme prop.
 *
 * Initial value, in priority order:
 *   1. what the user last chose (localStorage)
 *   2. light
 *
 * The OS preference is deliberately IGNORED: the product decision is that the
 * site opens light by default and dark mode is an explicit opt-in via the
 * toggle. That choice is persisted, so step 1 wins on every later visit.
 *
 * `index.html` carries a tiny inline script that applies the stored class before
 * this mounts. Without it the first paint is light and the dark theme appears a
 * frame later, which is a visible flash on every page load.
 */

const THEMES = ['light', 'dark']

/** The stored choice, or null when the user has never picked one. */
function storedTheme() {
  try {
    const value = localStorage.getItem(STORAGE_KEYS.theme)
    return THEMES.includes(value) ? value : null
  } catch {
    // Private-mode or a locked-down browser can throw on localStorage access.
    // A theme preference is not worth breaking the app over.
    return null
  }
}

/** What the OS is asking for right now. */
function systemTheme() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Kept out of the module's exports; the OS preference is no longer consulted. */
export default function ThemeProvider({ children }) {
  // No OS-preference listener: dark mode is opt-in only, so the initial state
  // is simply the saved choice or light.
  const [theme, setThemeState] = useState(() => storedTheme() ?? 'light')

  // Whether the user has made an explicit choice. Held in state (not derived
  // from localStorage on each render) so the effect below re-runs when it
  // changes.
  const [isExplicit, setIsExplicit] = useState(() => storedTheme() !== null)

  // Apply the theme to <html> and persist an explicit choice.
  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', theme === 'dark')
    // Tells the browser to draw native UI — scrollbars, form controls, the
    // canvas background — in the matching scheme. Without it a dark page still
    // gets a bright scrollbar on Windows.
    root.style.colorScheme = theme

    if (isExplicit) {
      try {
        localStorage.setItem(STORAGE_KEYS.theme, theme)
      } catch {
        /* Preference is best-effort; the app works without persistence. */
      }
    }
  }, [theme, isExplicit])

  const setTheme = useCallback((next) => {
    if (!THEMES.includes(next)) return
    setIsExplicit(true)
    setThemeState(next)
  }, [])

  const toggleTheme = useCallback(() => {
    setIsExplicit(true)
    setThemeState((previous) => (previous === 'dark' ? 'light' : 'dark'))
  }, [])

  const value = useMemo(
    () => ({ theme, isDark: theme === 'dark', setTheme, toggleTheme }),
    [theme, setTheme, toggleTheme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
