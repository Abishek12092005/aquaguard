import { NavLink, useLocation } from 'react-router-dom'

import Icon from '@/components/Icon'
import ThemeToggle from '@/components/ThemeToggle'
import { ICONS, findNavItem } from '@/config/navigation'
import { ROUTES } from '@/utils/constants'

/**
 * Top navigation bar.
 *
 * Carries only what the sidebar does not: the mobile menu trigger, the current
 * page name, the alert indicator, the theme switch and the Aqua AI launcher.
 * Navigation itself lives in the sidebar — repeating the full item list here as
 * well would be two controls doing one job.
 *
 * THERE IS NO ACCOUNT MENU. There is no user, so there is no profile to open and
 * nothing to sign out of; the menu is removed rather than replaced with a
 * placeholder, because an avatar that leads nowhere is a control that lies about
 * what the application can do.
 */
export default function Topbar({ onToggleSidebar, onToggleAquaAI, alertCount = 0 }) {
  const location = useLocation()

  const currentPage = findNavItem(location.pathname)

  return (
    // `fixed` on desktop, not `sticky`.
    //
    // `sticky top-0` is the obvious spelling and it does not work here: measured
    // on a document with 2387px of scroll, the header reported `top: -1800` once
    // the page had scrolled 1800px — it left the screen entirely, exactly like
    // the sidebar did before it was moved to `fixed`. A sticky element needs a
    // scrolling ancestor and room to travel within it, but the page is a column
    // of siblings under `min-h-screen`, so there is no ancestor whose box the
    // header can stick inside once the document itself is the scroller.
    //
    // `lg:left-64` is then required rather than optional: a fixed box positions
    // from the viewport edges, so it is unaffected by the content column's
    // `lg:pl-64` and would otherwise slide under the sidebar. 64 = the sidebar's
    // `lg:w-64`, so the two meet exactly.
    //
    // `right-0` rather than `inset-x-0` — `inset-x-0` would start at x=0 and
    // ignore `left-64`, spanning the full viewport width and covering the
    // sidebar.
    // FIXED ON EVERY BREAKPOINT, INCLUDING MOBILE.
    //
    // It was `sticky top-0` below `lg`, and sticky does not hold here — the page
    // body is a column of siblings under `min-h-screen` with no scrolling
    // ancestor for the header to stick inside, so on a phone it scrolled away with
    // the content. `fixed inset-x-0 top-0` takes the viewport as its containing
    // block unconditionally, so the bar stays put while the page scrolls under it.
    //
    // `lg:left-64` then applies from desktop up, so the fixed bar starts where the
    // fixed sidebar ends and the two meet exactly rather than overlapping.
    //
    // The bar's height is published as `--topbar-h` in `index.css`, and the page
    // content is padded by it, so nothing is hidden underneath — see `.app-topbar`.
    //
    // `z-30` IS THE TOP OF THE PAGE-CHROME STACK, and the one value every floating
    // panel must stay below. It is deliberately a ROUND number in a documented
    // ladder rather than an arbitrary one, because the bug it exists to prevent is
    // a floating panel picking the SAME value: at equal z-index DOM order decides,
    // and since `main` renders after this bar, an equal value silently loses the
    // header its own background. The ladder is:
    //
    //   z-20  in-page floating panels (the Location search suggestions)
    //   z-30  this bar — page chrome, above the scrolling content
    //   z-40  the mobile sidebar's backdrop
    //   z-50  the sidebar drawer, and the admin console's upload layer
    //
    // `bg-white` / `dark:bg-slate-900` are OPAQUE and on purpose: the bar is what
    // content disappears behind as it scrolls under. A translucent or transparent
    // bar would let the text underneath show through it.
    <header className="app-topbar fixed inset-x-0 top-0 z-30 bg-white lg:left-64 dark:bg-slate-900">
      <div className="flex h-16 items-center gap-2 px-3 sm:gap-3 sm:px-6">
        {/* Mobile menu trigger */}
        <button
          type="button"
          onClick={onToggleSidebar}
          className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-300 dark:hover:bg-black dark:hover:text-white lg:hidden"
          aria-label="Open navigation"
          aria-controls="app-sidebar"
        >
          <Icon path={ICONS.menu} className="h-5 w-5" />
        </button>

        {/* Current page — the sidebar is hidden on mobile, so the page name
            needs to be visible somewhere. */}
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold tracking-tight text-slate-900 dark:text-white">
            {currentPage?.label || 'AquaGuard AI'}
          </h1>
          <p className="hidden truncate text-xs text-slate-500 sm:block dark:text-slate-400">
            {currentPage?.description || 'AI-Based Water Quality Monitoring'}
          </p>
        </div>

        {/* Light/dark switch, before the alert bell: a display preference sits
            ahead of a notification in priority order. */}
        <ThemeToggle />

        {/* Alerts shortcut */}
        <NavLink
          to={ROUTES.alerts}
          className="relative rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-300 dark:hover:bg-black dark:hover:text-white"
          aria-label={alertCount > 0 ? `${alertCount} active alerts` : 'Alerts'}
        >
          <Icon path={ICONS.alerts} className="h-5 w-5" />
          {alertCount > 0 && (
            <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-unsafe px-1 text-[10px] font-semibold text-white">
              {alertCount > 9 ? '9+' : alertCount}
            </span>
          )}
        </NavLink>

        {/* Aqua AI launcher — the floating button is the primary entry point;
            this is the labelled affordance for people who look for one in the
            toolbar. Both toggle the same panel. */}
        <button
          type="button"
          onClick={onToggleAquaAI}
          className="hidden items-center gap-2 rounded-field border-aqua-200 bg-aqua-50 px-3 py-2 text-sm font-medium text-aqua-700 transition-colors hover:bg-aqua-100 hover:text-aqua-800 sm:inline-flex dark:border-aqua-700 dark:bg-aqua-900/50 dark:text-aqua-200 dark:hover:bg-aqua-800/60 dark:hover:text-white"
        >
          <span className="relative flex h-2 w-2" aria-hidden="true">
            <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-aqua-400" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-aqua-500" />
          </span>
          Aqua AI
        </button>
      </div>

      {/* Waterline under the bar: an aqua gradient hairline plus two waves
          drifting in opposite directions. This is the seam between the
          translucent header and the water behind it, so it reads as the
          surface rather than as a border. */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-4 overflow-hidden"
        aria-hidden="true"
      >
        <span className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-aqua-400/60 to-transparent" />
        <svg
          className="absolute bottom-0 left-0 h-3 w-[200%] text-aqua-300/50 motion-safe:animate-wave-mid"
          viewBox="0 0 1440 24"
          preserveAspectRatio="none"
          fill="currentColor"
        >
          <path d="M0,14 C240,2 480,22 720,12 C960,2 1200,20 1440,10 L1440,24 L0,24 Z" />
        </svg>
        <svg
          className="absolute bottom-0 left-0 h-3 w-[200%] text-aqua-400/40 motion-safe:animate-wave-slow"
          viewBox="0 0 1440 24"
          preserveAspectRatio="none"
          fill="currentColor"
        >
          <path d="M0,18 C260,8 520,24 780,15 C1040,6 1240,22 1440,13 L1440,24 L0,24 Z" />
        </svg>
      </div>
    </header>
  )
}
