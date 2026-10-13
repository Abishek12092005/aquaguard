import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import AppLayout from '@/components/AppLayout'
import IntroGate from '@/components/IntroGate'
import WaterLoader from '@/components/WaterLoader'
import { ROUTES } from '@/utils/constants'

// Route-level code splitting: opening the app does not download the prediction,
// history or console bundles.
const Home = lazy(() => import('@/pages/Home'))
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Predict = lazy(() => import('@/pages/Predict'))
const History = lazy(() => import('@/pages/History'))
const Alerts = lazy(() => import('@/pages/Alerts'))
const Reports = lazy(() => import('@/pages/Reports'))
const Location = lazy(() => import('@/pages/Location'))
const RainyAlerts = lazy(() => import('@/pages/RainyAlerts'))
const Admin = lazy(() => import('@/pages/Admin'))
const NotFound = lazy(() => import('@/pages/NotFound'))

/**
 * Application root.
 *
 * THE APPLICATION IS OPEN. There is no login, no registration and no profile:
 * every screen below is reachable by anyone, and the site boots straight to the
 * Home walkthrough. There is deliberately no auth provider wrapping the tree and
 * no route guard in front of any of this - a guard would only be a redirect to a
 * sign-in screen that no longer exists.
 *
 * Route structure:
 *
 *   AppLayout     sidebar + topbar + Aqua AI launcher
 *     /home /dashboard /predict /history /alerts /reports
 *     /location       Location Prediction — water source from a chosen place
 *     /rainy-alerts   Rainy Alerts — live rain for the device's own state
 *     /admin          the console, gated by ITS OWN credential on the page itself
 *
 * WHY THE CONSOLE IS NOT A PUBLIC OPTION. `/admin` is reachable, but reaching it
 * shows only the console's sign-in card: the real data is fetched behind an
 * unlocked server-side session that the console's own username and password
 * open, followed by a mailed confirmation. So it is not linked from the sidebar,
 * not offered to a visitor, and answers nothing without the credential - which
 * is what keeps it separate rather than making it a user option.
 *
 * The removed paths (`/login`, `/register`, `/profile`) are redirected rather
 * than 404'd, so an old bookmark lands on Home instead of a dead end.
 */
export default function App() {
  return (
    <Suspense fallback={<WaterLoader label="Loading…" />}>
      {/* PROMPT 14: the opening sea-water intro, shown once at the site entry
          point only. `IntroGate` is an OVERLAY, not a wrapper that withholds the
          tree — so the routes below mount, initialise and fetch immediately
          while the animation plays, and the Home page is revealed already warm
          rather than starting from scratch. Everything below is unchanged. */}
      <IntroGate>
        <Routes>
        <Route element={<AppLayout />}>
          <Route path={ROUTES.home} element={<Home />} />
          <Route path={ROUTES.dashboard} element={<Dashboard />} />
          <Route path={ROUTES.predict} element={<Predict />} />
          <Route path={ROUTES.history} element={<History />} />
          <Route path={ROUTES.alerts} element={<Alerts />} />
          <Route path={ROUTES.reports} element={<Reports />} />
          <Route path={ROUTES.location} element={<Location />} />
          <Route path={ROUTES.rainyAlerts} element={<RainyAlerts />} />

          {/* The console. Its gate lives in the page, because the gate is a
              credential rather than a session: see the note above. */}
          <Route path={ROUTES.admin} element={<Admin />} />

          {/* Unknown paths inside the app keep the shell, so a visitor can
              navigate away rather than hitting a dead end. */}
          <Route path="*" element={<NotFound />} />
        </Route>

        {/* --- Root ---
            A visitor arrives on the Home walkthrough rather than a dashboard of
            zeros, so the first thing they see is how the project works. */}
        <Route path="/" element={<Navigate to={ROUTES.home} replace />} />

        {/* --- Removed screens ---
            `/login`, `/register` and `/profile` no longer exist. They redirect
            to Home instead of 404ing, so a bookmark from before still lands
            somewhere useful. `replace` keeps the dead path out of history, so
            Back cannot walk into it again. */}
        <Route path="/login" element={<Navigate to={ROUTES.home} replace />} />
        <Route path="/register" element={<Navigate to={ROUTES.home} replace />} />
        <Route path="/profile" element={<Navigate to={ROUTES.home} replace />} />
        </Routes>
      </IntroGate>
    </Suspense>
  )
}
