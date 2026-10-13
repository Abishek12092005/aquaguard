/**
 * Navigation configuration.
 *
 * One list drives the sidebar, the mobile drawer and the breadcrumb, so the
 * three can never drift apart. Icons are inline SVG path data rather than an
 * icon-font dependency: five paths cost less than a package and cannot go
 * missing at build time.
 *
 * `end` matters for mapping active state. Without it, `/` would match every
 * route and every sidebar item would highlight at once.
 */

import { ROUTES } from '@/utils/constants'

/** SVG path definitions, shared by the sidebar and the page headers. */
export const ICONS = {
  // Dashboard is a bar chart, not a house: the screen it opens is a wall of
  // figures, and the house mark now belongs to Home where it means something.
  dashboard: 'M4 20h16M7 20v-6m5 6V8m5 12v-9',
  predict: 'M12 3c4 5 6 8 6 11a6 6 0 0 1-12 0c0-3 2-6 6-11Z',
  history: 'M12 8v4l3 2M3.05 11a9 9 0 1 1 .5 3M3 4v4h4',
  alerts: 'M12 3a6 6 0 0 0-6 6c0 5-2 6-2 6h16s-2-1-2-6a6 6 0 0 0-6-6Zm-2 16a2 2 0 1 0 4 0',
  analytics: 'M4 20V10m5 10V4m5 16v-7m5 7V8',
  // Reports: a document with lines of text, which is what the screen produces.
  reports: 'M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm2 5h6M9 12h6M9 16h4',
  // Location: a map pin, which is what the screen places.
  location: 'M12 21s-6.5-5.4-6.5-10a6.5 6.5 0 0 1 13 0c0 4.6-6.5 10-6.5 10Zm0-7.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z',
  // Rainy Alerts: a cloud with rain falling from it. A droplet alone would be
  // the water mark the whole app already uses three of; this has to be about
  // WEATHER falling, and distinct from the droplet in the brand.
  rain: 'M7 15a4 4 0 0 1 .6-7.96A5.5 5.5 0 0 1 18.4 8.5 3.75 3.75 0 0 1 17.5 15H7Zm1 2-.75 2.5M12 17l-.75 2.5M17 17l-.75 2.5',
  // Admin console: a shield, because the surface is privileged. Not in
  // NAV_ITEMS - the console is reached by its own URL and signs in with its own
  // credential, so it is not a destination offered in the navigation.
  admin: 'M12 3l7 3v6c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6l7-3Zm-2 9 1.5 1.5L15 10',
  // A person, for the console's user-management screen. Not an account avatar:
  // the application has no signed-in user, so this never appears beside a name.
  profile: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-8 9a8 8 0 0 1 16 0',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'M6 6l12 12M18 6L6 18',
  chevronRight: 'M9 6l6 6-6 6',
  // Brand mark, reusable wherever the droplet motif appears (sidebar, empty
  // states, the assistant avatar).
  droplet: 'M12 3c4 5 6 8 6 11a6 6 0 0 1-12 0c0-3 2-6 6-11Z',
  // Used by the polish pass for search fields and inline metadata.
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.35-4.35',
  refresh: 'M4 4v6h6M20 20v-6h-6M20 9A8 8 0 0 0 6 6M4 15a8 8 0 0 0 14 3',
  // Home is a plain house. The open book it used to be was a second metaphor
  // for the same idea and read as "documentation" in a sidebar of places;
  // a house says "start here" with no explanation needed, which is what the
  // dashboard icon no longer claims now that it is a chart.
  home: 'M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5M9.5 21v-6h5v6',
  check: 'M20 6 9 17l-5-5',
  info: 'M12 16v-5m0-3h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z',
  shield: 'M12 3l7 3v6c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6l7-3Z',
  send: 'M4 12h15M13 6l6 6-6 6',
  // Theme toggle. Drawn as a sun and a crescent rather than a switch, so the
  // button says which mode it moves TO on the icon alone.
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 1v2m0 18v2M4.2 4.2l1.4 1.4m12.8 12.8 1.4 1.4M1 12h2m18 0h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z',
}

/**
 * The sections of the application, in sidebar order.
 *
 * `description` is used by the page header, so each screen states its purpose
 * rather than relying on the title alone.
 *
 * NO ACCOUNT ENTRY, and no console entry. The application is open, so there is
 * no user, no profile and nothing to log out of. The admin console is
 * deliberately absent too: it is a separate surface reached by its own URL and
 * guarded by its own credential, and listing it here would offer it to every
 * visitor as an ordinary destination.
 *
 * THE TWO WAYS TO PREDICT ARE BOTH HERE AND BOTH ARE NAMED FOR WHAT THEY ASK OF
 * THE VISITOR. "Location Prediction" identifies a water source from a place and
 * hands the readings over; "Manual Prediction" is the visitor typing their own.
 * The labels say which one a screen is before it is opened.
 *
 * "Rainy Alerts" is weather, not water quality: it reads the device's own
 * location and reports the rain situation for that STATE. It is a separate screen
 * because it answers a different question and needs a different permission, and
 * it is deliberately NOT part of Location Prediction any more.
 */
export const NAV_ITEMS = [
  {
    to: ROUTES.home,
    label: 'Home',
    icon: ICONS.home,
    description: 'How AquaGuard AI works and how to use it',
  },
  {
    to: ROUTES.dashboard,
    label: 'Dashboard',
    icon: ICONS.dashboard,
    description: 'Your water quality at a glance',
  },
  {
    to: ROUTES.location,
    label: 'Location Prediction',
    icon: ICONS.location,
    description: 'Identify a water source from a place, nearby sources and risks',
  },
  {
    to: ROUTES.predict,
    label: 'Manual Prediction',
    icon: ICONS.predict,
    description: 'Enter the readings yourself and get a potability verdict',
  },
  {
    to: ROUTES.history,
    label: 'Prediction History',
    icon: ICONS.history,
    description: 'Every reading submitted, newest first, with search and filters',
  },
  {
    to: ROUTES.alerts,
    label: 'Alerts',
    icon: ICONS.alerts,
    description: 'Notifications for unsafe water readings',
  },
  {
    to: ROUTES.reports,
    label: 'Reports',
    icon: ICONS.reports,
    description: 'Full reports with CSV and PDF downloads',
  },
  {
    to: ROUTES.rainyAlerts,
    label: 'Rainy Alerts',
    icon: ICONS.rain,
    description: 'Live rain warnings for the state this device is in',
  },
]

/** Resolve the nav item matching a pathname, for breadcrumbs and headers. */
export function findNavItem(pathname) {
  return (
    NAV_ITEMS.find((item) => item.to === pathname) ||
    NAV_ITEMS.find((item) => pathname.startsWith(`${item.to}/`)) ||
    null
  )
}
