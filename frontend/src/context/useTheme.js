import { useContext } from 'react'

import ThemeContext from '@/context/themeContextObject'

/**
 * Access the current theme and the controls for changing it.
 *
 * Kept out of the provider's module for the same reason as the other hooks: a
 * file
 * exporting both a component and a plain function breaks React Fast Refresh.
 *
 * Returns a safe default when no provider is mounted, so a component rendered in
 * isolation (a test, a future standalone screen) still works — it just always
 * reports light and the toggles do nothing.
 */
export function useTheme() {
  return (
    useContext(ThemeContext) ?? {
      theme: 'light',
      isDark: false,
      setTheme: () => { },
      toggleTheme: () => { },
    }
  )
}

export default useTheme
