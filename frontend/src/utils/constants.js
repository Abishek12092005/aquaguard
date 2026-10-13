/**
 * Shared client-side constants.
 *
 * The authoritative source for parameter metadata is the backend
 * (`GET /api/dashboard/parameters`) and the prediction form is generated from
 * it. The mirrored values here are a fallback so the UI still renders if that
 * request fails, and they are kept deliberately in step with
 * backend/app/constants.py.
 */

// Base URL of the backend API.
//
// Two names are accepted deliberately:
//
//   VITE_API_URL        the documented name for a deployment
//   VITE_API_BASE_URL   the original name, kept working so an existing .env or
//                       CI configuration does not break on upgrade
//
// `VITE_API_URL` wins when both are set, so the documented variable is
// authoritative. In development neither is needed: vite.config.js proxies
// `/api` to Flask, which keeps the browser same-origin and stops CORS from
// masking a real failure.
//
// Only VITE_-prefixed variables reach the browser, which is correct here - this
// is a public URL, not a secret. The Aqua AI key is server-side only and
// deliberately has no VITE_ variant.
const API_URL = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL || '/api'

export const API_BASE_URL = API_URL

export const APP_NAME = import.meta.env.VITE_APP_NAME || 'AquaGuard AI'

/** Water quality parameters, in the canonical model order. */
export const FEATURE_NAMES = ['ph', 'turbidity', 'tds', 'temperature', 'dissolved_oxygen']

/** Display labels, units and input constraints for each parameter.
 *
 * `placeholder` is EXAMPLE text only - it shows the shape of a typical reading
 * in the empty box and is never a value: the inputs stay blank until the visitor
 * types their own test result. */
export const FEATURE_META = {
  ph: { label: 'pH', unit: 'pH', min: 0, max: 14, step: 0.01, placeholder: 'Example: 7.2' },
  turbidity: { label: 'Turbidity', unit: 'NTU', min: 0, max: 1000, step: 0.01, placeholder: 'Example: 1.0 NTU' },
  tds: { label: 'Total Dissolved Solids', unit: 'mg/L', min: 0, max: 50000, step: 0.01, placeholder: 'Example: 350 mg/L' },
  temperature: { label: 'Temperature', unit: '°C', min: -5, max: 100, step: 0.01, placeholder: 'Example: 27 °C' },
  dissolved_oxygen: { label: 'Dissolved Oxygen', unit: 'mg/L', min: 0, max: 20, step: 0.01, placeholder: 'Example: 6.8 mg/L' },
}

export const ROUTES = {
  home: '/home',
  dashboard: '/dashboard',
  reports: '/reports',
  predict: '/predict',
  history: '/history',
  alerts: '/alerts',
  // Location-based water quality: the surface where a user picks their location
  // and the app identifies the water source, distance, risks before handing the
  // pre-filled parameters to the Manual Prediction page.
  location: '/location',
  // Rainy Alerts: live rain warnings for the STATE this device is in, from the
  // browser's own geolocation. A separate screen from Location Prediction
  // because it answers a weather question rather than a water-source one, and
  // because it needs a location permission the other screens do not require.
  rainyAlerts: '/rainy-alerts',
  admin: '/admin',
}

// Navigation lives in `@/config/navigation` (items carry icons and
// descriptions). Re-exported here so existing imports keep working.

export const RISK_LEVELS = {
    safe: 'safe',
    moderate: 'moderate',
    unsafe: 'unsafe',
  }

/**
 * localStorage keys.
 *
 * THE APPLICATION IS OPEN - there is no user login, so no access token and no
 * cached user are stored. Only the theme preference is persisted, and that is a
 * display choice rather than a credential: it is read on first paint to set the
 * theme before React mounts, which is what prevents a light flash on a
 * dark-set screen.
 */
export const STORAGE_KEYS = {
    // The user's explicit light/dark choice. Not a credential — it is read on
    // first paint to set the theme before React mounts, which is what prevents
    // a light flash on a dark-set screen.
    theme: 'aquaguard.theme',
    // THE ADMIN APPROVAL WATCH. `sessionStorage`, so it is scoped to this tab and
    // dies with it — the same store the browser challenge has always been meant to
    // use. It holds the pending request id and the challenge, so a reload, a
    // network drop or a laptop that slept can RESUME watching the outcome instead
    // of losing it and forcing a fresh sign-in. Neither value is an authorisation
    // on its own: the request id is a non-secret handle, and the challenge is
    // checked server-side and never accepted from anywhere but this tab.
    adminApprovalWatch: 'aquaguard.adminApprovalWatch',
}
