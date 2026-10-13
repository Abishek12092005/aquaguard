import { useCallback, useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import AquaAIButton from '@/components/AquaAI'
import LocationPermissionPrompt from '@/components/LocationPermissionPrompt'
import Sidebar from '@/components/Sidebar'
import Topbar from '@/components/Topbar'
import WaterBackground from '@/components/WaterBackground'
import { FEATURES } from '@/config/features'
import { findNavItem } from '@/config/navigation'
import AquaAIProvider from '@/context/AquaAIContext'
import DeviceLocationProvider from '@/context/DeviceLocationContext'
import { useApi } from '@/hooks/useApi'
import { REFRESH_GROUPS, useDataRefresh } from '@/utils/dataRefresh'
import { alertApi } from '@/api'
import { APP_NAME } from '@/utils/constants'

/**
 * Shell for every screen.
 *
 * Owns the two pieces of state that the sidebar and topbar share:
 *   - the mobile drawer's open/closed state
 *   - the alert count, fetched once here rather than in each of them
 *
 * Responsive behaviour:
 *   mobile   sidebar is an off-canvas drawer; the topbar shows the page name
 *   tablet   same drawer, wider content padding
 *   desktop  sidebar is a viewport-pinned column; the topbar's menu button is
 *            hidden
 *
 * Because the desktop column is `position: fixed` (see Sidebar), it is out of
 * flow rather than a flex sibling. `lg:pl-64` on the content column reserves
 * exactly the sidebar's width so the two never overlap; `body { overflow-x:
 * hidden }` is the backstop if they ever do.
 *
 * The animated water backdrop lives here, not per page, so every screen shares
 * one instance — the rain keeps falling across a route change
 * instead of restarting, and only one set of animations is ever in the DOM.
 */
export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [aquaAIOpen, setAquaAIOpen] = useState(false)
  const location = useLocation()

  // THE BROWSER TITLE, derived from the SAME nav item the sidebar and the
  // topbar use. It was the one place a screen's name still appeared in its old
  // form - the tab said "AquaGuard AI" for every screen, so renaming a page
  // could not reach it and nothing about the title was ever wrong in a way
  // anyone could check.
  //
  // One source, not a per-page string repeated in each file: `findNavItem` is
  // already the definition of a screen's name, so a rename in `navigation.js`
  // moves the tab along with the sidebar and the heading. A path the nav does
  // not know (the console, the not-found page) falls back to the app name rather
  // than showing nothing.
  const pageTitle = findNavItem(location.pathname)?.label
  useEffect(() => {
    document.title = pageTitle ? `${pageTitle} · ${APP_NAME}` : APP_NAME
  }, [pageTitle])

  // One request feeds the badge in both navigation surfaces.
  //
  // Only fired when the alerts service is actually implemented. Calling it
  // regardless would produce a guaranteed 501 on every page load, filling the
  // console with errors that mean nothing — and teaching the reader to ignore
  // the console, which is precisely where a real failure would show up.
  const { data: alertSummary, refetch: refetchAlertSummary } = useApi(
    () => (FEATURES.alerts ? alertApi.summary() : Promise.resolve(null)),
    [FEATURES.alerts],
  )
  const alertCount = alertSummary?.data?.active ?? 0
  // The badge is owned here, but the alerts are marked read on the Alerts page.
  // Without this subscription the count was fetched once on mount and then
  // frozen: marking an alert read updated the Alerts page's own tiles while the
  // bell in the topbar and the sidebar badge kept showing the old number, which
  // reads as the button having done nothing.
  useDataRefresh(REFRESH_GROUPS.alerts, refetchAlertSummary)

  const closeSidebar = useCallback(() => setSidebarOpen(false), [])

  // Any navigation closes the drawer, so a tap on a sidebar link does not
  // leave an overlay covering the page that was just requested.
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  // Lock body scroll while the drawer is open, otherwise the page behind it
  // scrolls under the user's finger on touch devices.
  useEffect(() => {
    if (sidebarOpen) {
      const previous = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      return () => {
        document.body.style.overflow = previous
      }
    }
    return undefined
  }, [sidebarOpen])

  return (
    // The providers wrap the shell so the page (via <Outlet />), the assistant
    // panel and the global location popup share one context each. A page
    // announces what is on screen; the panel turns that into the right prompts.
    // The device-location provider sits OUTSIDE the Aqua AI one so every screen
    // — including the assistant — can read one authorised location.
    <DeviceLocationProvider>
    <AquaAIProvider>
      {/* The backdrop is `fixed`, so it needs no positioning context here and
          contributes nothing to layout — it simply paints behind this shell. */}
      <WaterBackground variant="app" />

      <div className="relative flex min-h-screen">
        <Sidebar isOpen={sidebarOpen} onClose={closeSidebar} alertCount={alertCount} />

        <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
          <Topbar
            onToggleSidebar={() => setSidebarOpen((open) => !open)}
            // A REAL TOGGLE. This used to hard-set `true`, so the topbar's
            // Aqua AI button could OPEN the assistant and then never close it —
            // pressing it again did nothing. The panel now writes its own open
            // state back through `onOpenChange`, and this flips it, so the
            // control means the same thing as the floating launcher.
            onToggleAquaAI={() => setAquaAIOpen((open) => !open)}
            alertCount={alertCount}
          />

          {/* max-w bounds the line length on ultra-wide monitors; min-w-0 lets
              wide tables scroll instead of stretching the whole layout, which
              is what prevents horizontal page overflow on small screens.

              THE BAR IS FIXED ON EVERY BREAKPOINT NOW, so the content has to
              clear it everywhere, not only at `lg`. `.app-content` in index.css
              adds the bar's height (`--topbar-h`) as top padding at every width;
              the `lg:pt-24` it replaces only covered desktop. The result is the
              same 6rem gap at `lg` (4rem bar + 2rem page padding) and a correct
              gap below `lg`, where the header previously overlapped the first
              block of every page once it stopped scrolling away. */}
          <main className="app-content mx-auto min-w-0 w-full max-w-7xl flex-1 px-4 pb-6 sm:px-6 sm:pb-7 lg:px-8 lg:pb-8">
            <Outlet />
          </main>

          <footer className="border-t border-slate-200 bg-white px-4 py-6 sm:px-6 lg:px-8 dark:border-slate-700 dark:bg-slate-900">
            <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-2 text-center text-xs text-slate-400 sm:flex-row sm:text-left">
              <p>AquaGuard AI — AI-Based Water Quality Monitoring &amp; Prediction System</p>
              <p className="font-medium text-slate-500 dark:text-slate-400">
                Not a substitute for laboratory testing
              </p>
            </div>
          </footer>
        </div>

        <AquaAIButton open={aquaAIOpen} onOpenChange={setAquaAIOpen} />

        {/* THE GLOBAL LOCATION-PERMISSION POPUP.

            Mounted in the SHELL, so it appears on every screen — the brief
            requires it regardless of which page the visitor is on, and a prompt
            owned by any single page could not satisfy that. It sits inside the
            DeviceLocationProvider because it reads and writes that shared
            state, and it renders through a portal, so it paints above all page
            chrome wherever its trigger sits in the tree.

            The provider wraps the whole shell so Rainy Alerts and Location
            Prediction read the SAME granted location rather than each asking the
            browser again. */}
        <LocationPermissionPrompt />
      </div>
    </AquaAIProvider>
    </DeviceLocationProvider>
  )
}
