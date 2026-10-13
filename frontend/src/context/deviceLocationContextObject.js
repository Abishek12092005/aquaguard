/**
 * The device-location context object.
 *
 * Split from its provider and hook (the same three-file shape Aqua AI uses) so
 * React Fast Refresh keeps working: this module exports only a `createContext`
 * value, never a component.
 *
 * WHY THIS EXISTS. The location permission is asked ONCE, globally, and the
 * answer — the resolved place, or a refusal — has to be readable from more than
 * one screen: Rainy Alerts reads the state to fetch real alerts for it, and
 * Location Prediction uses the same authorised position instead of asking
 * again. Before this, each screen asked the browser separately, so the user
 * could be prompted more than once and two screens could hold different
 * answers.
 *
 * WHAT IT HOLDS, AND WHAT IT DELIBERATELY DOES NOT.
 *
 *   status    'idle' | 'prompting' | 'locating' | 'granted' | 'denied' | 'unsupported'
 *   place     the reverse-geocoded, PLACE-LEVEL result — name, area, city,
 *             district, state, country, pincode — or null
 *   coords    the browser's own last fix ({ lat, lon }) when one was obtained,
 *             kept in memory only so a screen can re-resolve if it needs to
 *
 * No coordinate is persisted to storage, and no place is invented: an unresolved
 * point leaves `place` null and the screens say so. The exact coordinates are
 * never rendered anywhere — the place name is what the UI shows.
 */
import { createContext } from 'react'

const DeviceLocationContext = createContext(null)

export default DeviceLocationContext

/** The permission states, so callers compare against names, not bare strings. */
export const LOCATION_STATUS = {
  idle: 'idle',
  prompting: 'prompting',
  locating: 'locating',
  granted: 'granted',
  denied: 'denied',
  unsupported: 'unsupported',
}

/**
 * Turn the browser's numeric `PositionError.code` into a NAME a screen can act on.
 *
 * The Geolocation API reports failures as `1` / `2` / `3`, which is unreadable at
 * a call site and easy to get wrong. Mapping them once, here, means the provider
 * and every screen share one vocabulary:
 *
 *   1 -> 'PERMISSION_DENIED'      the visitor refused the browser dialog
 *   2 -> 'POSITION_UNAVAILABLE'   no GPS fix / location services off
 *   3 -> 'TIMEOUT'                the device did not answer in time
 *   anything else -> 'POSITION_UNAVAILABLE'
 *
 * A pure function with no React and no imports, so it can be unit-tested for
 * every state without a browser.
 */
export function normaliseGeoErrorCode(errorCode) {
  if (errorCode === 1) return 'PERMISSION_DENIED'
  if (errorCode === 3) return 'TIMEOUT'
  if (errorCode === 2) return 'POSITION_UNAVAILABLE'
  return 'POSITION_UNAVAILABLE'
}
