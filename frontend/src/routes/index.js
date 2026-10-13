/**
 * Route table.
 *
 * The authoritative routes live in `App.jsx` (declarative, with guards and
 * layout nesting). This module exports the same paths plus navigation helpers
 * so non-component code — notably Aqua AI's `navigate_to_page` tool — has a
 * single import site instead of hardcoding URL strings.
 */

import { ROUTES } from '@/utils/constants'

export { ROUTES }

export const NAV_ROUTES = [
  ROUTES.home,
  ROUTES.dashboard,
  ROUTES.predict,
  ROUTES.history,
  ROUTES.alerts,
  ROUTES.reports,
  ROUTES.location,
  ROUTES.rainyAlerts,
]

/** Titles used by the Aqua AI panel and the navbar tooltips. */
export const ROUTE_TITLES = {
  [ROUTES.home]: 'Home',
  [ROUTES.dashboard]: 'Dashboard',
  [ROUTES.predict]: 'Manual Prediction',
  [ROUTES.history]: 'Prediction History',
  [ROUTES.alerts]: 'Alerts',
  [ROUTES.reports]: 'Reports',
  [ROUTES.location]: 'Location Prediction',
  [ROUTES.rainyAlerts]: 'Rainy Alerts',
}

/** True when a path is one Aqua AI is permitted to navigate to. */
export function isAllowedRoute(path) {
  return NAV_ROUTES.includes(path)
}
