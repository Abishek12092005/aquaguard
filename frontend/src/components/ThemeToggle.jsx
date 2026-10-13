import Icon from '@/components/Icon'
import { ICONS } from '@/config/navigation'
import { useTheme } from '@/context/useTheme'

/**
 * Light/dark switch.
 *
 * Shows the icon for the mode you would move TO, not the one you are in — a
 * button labelled with the current state is ambiguous ("is this telling me what
 * I have, or what I get?"), and on a toggle that is the whole question. The
 * accessible name says it explicitly, so the icon never has to carry it alone.
 *
 * The two icons are cross-faded and rotated past each other rather than swapped
 * instantly: an instant swap reads as a repaint, whereas the transition reads as
 * one control changing state.
 */
export default function ThemeToggle({ className = '' }) {
  const { isDark, toggleTheme } = useTheme()

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-pressed={isDark}
      className={`relative rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-300 dark:hover:bg-black dark:hover:text-white ${className}`}
    >
      <span className="relative block h-5 w-5">
        {/* Sun — shown in dark mode, i.e. "click for light". */}
        <Icon
          path={ICONS.sun}
          className={`absolute inset-0 h-5 w-5 transition-all duration-300 ${isDark ? 'rotate-0 opacity-100' : '-rotate-90 opacity-0'
            }`}
        />
        {/* Moon — shown in light mode, i.e. "click for dark". */}
        <Icon
          path={ICONS.moon}
          className={`absolute inset-0 h-5 w-5 transition-all duration-300 ${isDark ? 'rotate-90 opacity-0' : 'rotate-0 opacity-100'
            }`}
        />
      </span>
    </button>
  )
}
