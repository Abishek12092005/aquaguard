import { NavLink } from 'react-router-dom'

import AquaGuardLogo from '@/components/AquaGuardLogo'
import Icon from '@/components/Icon'
import { ICONS, NAV_ITEMS } from '@/config/navigation'
import { APP_NAME, ROUTES } from '@/utils/constants'

/**
 * Left navigation.
 *
 * Two behaviours in one component:
 *   lg and up  `position: fixed` column pinned to the viewport, always visible
 *   below lg   off-canvas drawer, slid in by the navbar's menu button
 *
 * Desktop started out as `lg:sticky lg:top-0 lg:h-screen`, which is the obvious
 * spelling and is still wrong here. `lg:h-screen` only pins the column while the
 *document* is what scrolls; the page body is exactly `h-screen` whenever a
 * screen's own scroller (the history table, a detail pane) is the thing doing the
 * scrolling, and at that point `sticky` has nothing to stick to — the column
 * rides off the top of the viewport with the rest of the content. `fixed` takes
 * the viewport as its containing block unconditionally, so the sidebar stays put
 * whether the document, a nested scroller, or an inner pane is scrolling.
 *
 * `lg:h-screen` gives the sidebar its own viewport-tall box; the inner <nav> is
 * the only thing that scrolls, so a long item list stays reachable on a short
 * window without ever moving the brand.
 *
 * Only one element is rendered, switched by CSS breakpoints rather than
 * duplicated markup, so there is a single source of truth for the item list
 * and the active state.
 *
 * There is NO ACCOUNT BLOCK at the foot. There is no user, so there is nothing
 * to name, nothing to open a profile for and nothing to log out of - and an
 * empty avatar with a dead "Log out" beside it would be worse than nothing.
 */
export default function Sidebar({ isOpen, onClose, alertCount = 0 }) {
  return (
    <>
      {/* Backdrop, mobile only. Clicking it dismisses the drawer, which is
          what a user expects from an overlay. */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        id="app-sidebar"
        className={`fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-slate-200 bg-white transition-transform duration-200 ease-out lg:h-screen lg:w-64 lg:translate-x-0 dark:border-slate-700 dark:bg-slate-900 ${
          isOpen ? 'translate-x-0 shadow-2xl lg:shadow-none' : '-translate-x-full'
        }`}
        aria-label="Main navigation"
      >
        {/* --- Brand --- */}
        <div className="relative flex h-16 shrink-0 items-center justify-between overflow-hidden border-b border-aqua-100/80 px-4 dark:border-slate-700/80">
          {/* Miniature waterline inside the brand bar: two waves scrolling
              against each other, so the app's identity is itself animated
              rather than a static logo above an animated page. */}
          <span
            className="pointer-events-none absolute inset-x-0 bottom-0 h-6 overflow-hidden"
            aria-hidden="true"
          >
            <svg
              className="absolute bottom-0 left-0 h-6 w-[200%] text-aqua-300/40 motion-safe:animate-wave-mid"
              viewBox="0 0 1440 40"
              preserveAspectRatio="none"
              fill="currentColor"
            >
              <path d="M0,22 C240,4 480,36 720,20 C960,4 1200,32 1440,18 L1440,40 L0,40 Z" />
            </svg>
            <svg
              className="absolute bottom-0 left-0 h-6 w-[200%] text-aqua-400/30 motion-safe:animate-wave-slow"
              viewBox="0 0 1440 40"
              preserveAspectRatio="none"
              fill="currentColor"
            >
              <path d="M0,28 C260,12 520,40 780,26 C1040,12 1240,36 1440,24 L1440,40 L0,40 Z" />
            </svg>
          </span>

          {/* The brand mark goes to Home rather than the Dashboard: it is the
              "start again" affordance, and the walkthrough is where a user who
              is lost wants to land. --- */}
          <NavLink
            to={ROUTES.home}
            className="relative flex items-center gap-2.5"
            onClick={onClose}
          >
            {/* The brand mark: droplet feeding a neural network. Replaces the
                flat droplet glyph, so the app's identity states what it does —
                machine learning applied to water — instead of only the water
                half of it. */}
            <AquaGuardLogo size={36} />
            {/* Just the wordmark. The "Water Quality" line that used to sit under
                it has been removed, so the brand block is the logo and the name
                and nothing else. */}
            <span className="text-sm font-semibold tracking-tight text-slate-900 dark:text-white">
              {APP_NAME}
            </span>
          </NavLink>

          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900 lg:hidden dark:text-slate-300 dark:hover:bg-black dark:hover:text-white"
          >
            <span className="sr-only">Close navigation</span>
            <Icon path={ICONS.close} className="h-5 w-5" />
          </button>
        </div>

        {/* --- Items --- */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4" aria-label="Sections">
          {NAV_ITEMS.map((item) => {
            const badge = item.badgeKey === 'alerts' ? alertCount : 0
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onClose}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-field px-3 py-2.5 text-sm font-medium transition-colors duration-150 ${
                    isActive
                      ? 'bg-aqua-50 text-aqua-700 ring-1 ring-inset ring-aqua-100 dark:bg-aqua-900/60 dark:text-aqua-200 dark:ring-aqua-800'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-black dark:hover:text-white'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon
                      path={item.icon}
                      className={`h-5 w-5 shrink-0 transition-colors ${
                        isActive
                          ? 'text-aqua-600 dark:text-aqua-300'
                          : 'text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-200'
                      }`}
                    />
                    <span className="flex-1 truncate">{item.label}</span>

                    {badge > 0 && (
                      <span
                        className="shrink-0 rounded-full bg-unsafe px-2 py-0.5 text-2xs font-semibold tabular text-white"
                        aria-label={`${badge} active alerts`}
                      >
                        {badge > 99 ? '99+' : badge}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            )
          })}

          {/* --- Admin console (separate, gated surface) ---
              Kept OUT of NAV_ITEMS because it is not a visitor screen: it has
              its own credential, its own sign-in, and it must not be mistaken
              for part of the water-quality flow. Rendered last, under a visual
              divider, so it reads as "operator area" rather than another page. */}
          <div className="mt-4 border-t border-slate-200 pt-4 dark:border-slate-700">
            <NavLink
              to={ROUTES.admin}
              onClick={onClose}
              className={({ isActive }) =>
                `group flex items-center gap-3 rounded-field px-3 py-2.5 text-sm font-medium transition-colors duration-150 ${
                  isActive
                    ? 'bg-aqua-50 text-aqua-700 ring-1 ring-inset ring-aqua-100 dark:bg-aqua-900/60 dark:text-aqua-200 dark:ring-aqua-800'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-black dark:hover:text-white'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    path={ICONS.admin}
                    className={`h-5 w-5 shrink-0 transition-colors ${
                      isActive
                        ? 'text-aqua-600 dark:text-aqua-300'
                        : 'text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-200'
                    }`}
                  />
                  <span className="flex-1 truncate">Admin</span>
                </>
              )}
            </NavLink>
          </div>
        </nav>
      </aside>
    </>
  )
}
