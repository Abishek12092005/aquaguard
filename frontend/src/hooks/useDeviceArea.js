/**
 * useDeviceArea - the ADMINISTRATIVE AREA THIS DEVICE IS IN (Step 9).
 *
 * The Location Prediction autocomplete ranks local places first, and "local"
 * has to mean the state the device is really in. That is read here, once, from
 * the browser's own geolocation, and handed to the backend as a RANKING
 * PREFERENCE. Three rules govern the whole hook, and all three come straight
 * from the feature's own wording:
 *
 *   1. IT IS A PREFERENCE, NEVER A CONSTRAINT. The value only reorders the
 *      suggestions the search already returned. A user in Tamil Nadu who types
 *      "Bengaluru" still gets Bengaluru - nothing is filtered, and the backend
 *      is given no ability to remove a place.
 *
 *   2. DENIAL IS A NORMAL OUTCOME, NOT AN ERROR. When the permission is
 *      refused, unavailable, or the browser has no geolocation at all, this
 *      resolves to `{ state: null, district: null, status: 'denied' }` and the
 *      page does nothing differently. The user is never prompted again, never
 *      shown an error about it, and the search behaves exactly as it did before
 *      this feature existed.
 *
 *   3. IT NEVER ASKS THE BROWSER FOR A POSITION. Not even silently. This is
 *      the rule that decides the whole shape of the hook. A ranking PREFERENCE
 *      is not worth a second request beside the popup the brief names as the
 *      ONE consent - and while the browser permission is still `prompt`, any
 *      request from here would raise the browser's own dialog in addition to
 *      the app's popup, so the visitor would be asked twice. The hook
 *      therefore consumes the shared provider's fix and never calls
 *      `getCurrentPosition` at all.
 *
 * NOTHING IS HARDCODED AND NOTHING IS ASSUMED. There is no default state, no
 * fallback country, no IP-based guess and no cached value from a previous visit:
 * the area is whatever the reverse-geocode of this device's own fix says it is,
 * or nothing at all. A fix that lands in the sea, or in a country the geocoder
 * cannot name, simply yields no state - which degrades to the general search.
 *
 * THE FIX COMES FROM THE ONE OWNER - THE POPUP'S ALLOW. There is exactly one
 * place in the application that asks the browser for a position on a visitor's
 * behalf - the shared `DeviceLocationContext`, driven by the blue consent
 * popup's Allow button - and this hook now consumes THAT fix and nothing else.
 * It used to run its own `getCurrentPosition` on mount (and later a
 * permission-gated silent one); both are gone. Any request made here, however
 * quiet, would be a second ask beside the popup the brief names as the one
 * consent. So the hook waits for the shared fix and reverse-geocodes it. The
 * coordinates go to the server for one reverse-geocode and are then discarded,
 * exactly as on every other path - they are never stored, and the only thing
 * that survives this hook is a state and a district NAME.
 *
 * A HOOK, NOT A SCREEN, SO IT DEGRADES SILENTLY. Every caller uses the area to
 * REORDER suggestions it already has; none of them needs the area to function.
 * When it cannot be had - no permission, no fix, no geolocation, no reverse-
 * geocode - the hook resolves to nulls and the caller behaves as it did before
 * this feature existed.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { locationApi } from '@/api'
import useDeviceLocation from '@/context/useDeviceLocation'

/**
 * Pull the administrative levels out of a resolved place.
 *
 * Nominatim and Open-Meteo disagree about which keys carry a state - one calls
 * it `state`, the other `region`; the district is `county` or `district`, and
 * the neighbourhood is `neighbourhood` or `suburb`. Every known key is read and
 * the best available is taken, so a provider renaming a field does not silently
 * turn the preference off. `suburb`/`neighbourhood` are deliberately EXCLUDED
 * from the district: a neighbourhood is smaller than the district the user is
 * ranking by, and passing one would narrow the preference to a single locality.
 */
function readArea(place) {
  if (!place || typeof place !== 'object') return null
  const pick = (...keys) => {
    for (const key of keys) {
      const value = place[key]
      if (typeof value === 'string' && value.trim()) return value.trim()
    }
    return null
  }
  const state = pick('state', 'region', 'admin1')
  const district = pick('district', 'county', 'admin2')
  // No state means no usable preference. A district on its own is not enough:
  // the same district name exists in several states, so ranking on it alone
  // would be a guess.
  if (!state) return null
  return { state, district }
}

/**
 * The hook. Returns `{ state, district, status }` and never throws.
 *
 * `status` is one of:
 *   'idle'      not looked up yet
 *   'locating'  a fix or the reverse-geocode is in flight
 *   'ready'     the device's state is known
 *   'denied'    refused, unsupported, or unresolvable - use the general search
 *   'error'     the lookup failed - also the general search
 *
 * Only 'ready' carries an area. Every other status carries nulls, so a caller
 * that ignores the status entirely still behaves correctly.
 */
export default function useDeviceArea() {
  const [area, setArea] = useState({ state: null, district: null })
  const [status, setStatus] = useState('idle')

  // THE SHARED FIX, IF ONE HAS BEEN OBTAINED. The provider owns the single
  // browser request; whenever it holds coordinates - because the visitor
  // allowed the app's popup, or because a screen's "Use my location" ran - this
  // hook uses them instead of asking the browser again.
  const sharedLocation = useDeviceLocation()
  const sharedCoords = sharedLocation?.coords

  // The area is resolved at most once: a fix is reverse-geocoded into a state
  // and district, and the useful answer never changes for the life of the mount
  // (a device does not cross a state line mid-search). This guards both the
  // reverse-geocode and the silent fallback request below.
  const resolvedOnce = useRef(false)

  /**
   * Reverse-geocode one fix into `{ state, district }` and publish it.
   *
   * The only thing this hook does with coordinates. The endpoint is the same
   * one "Use my location" uses, and the coordinates are discarded as soon as
   * the place fields are read - only the state and district NAMES survive.
   */
  const resolveFromFix = useCallback(async (latitude, longitude) => {
    setStatus('locating')
    try {
      const response = await locationApi.reverse({ lat: latitude, lon: longitude })
      const found = readArea(response?.data)
      if (found) {
        setArea(found)
        setStatus('ready')
      } else {
        // Resolved, but to somewhere with no state - open sea, a disputed
        // border, a place the geocoder names only at country level. There is no
        // state to prefer, so there is no preference. An honest "no
        // preference", never a substitute one.
        setStatus('denied')
      }
    } catch {
      // The server refused or could not resolve. Same outcome as a refusal.
      setStatus('error')
    }
  }, [])

  // ONE: consume a fix the SHARED PROVIDER already obtained.
  //
  // This is the ONLY path, and deliberately so. The brief is explicit that the
  // location must be taken FROM the app's own popup - its Allow is the one
  // consent, and it must be the one request. The visitor allows the popup; the
  // provider takes the fix; this hook reads it here and resolves the area. This
  // hook therefore makes NO browser request of its own at all, ever - not even a
  // silent one - so no dialog of any kind can come from it, and the popup's
  // Allow is the single ask the visitor answers.
  //
  // If no fix ever arrives (the visitor declined, or never answered), the area
  // simply stays unknown and the suggestions rank without a local preference -
  // the honest degradation the hook was always designed for.
  useEffect(() => {
    if (resolvedOnce.current) return
    const lat = sharedCoords?.lat
    const lon = sharedCoords?.lon
    if (typeof lat !== 'number' || typeof lon !== 'number') return
    resolvedOnce.current = true
    resolveFromFix(lat, lon)
  }, [sharedCoords?.lat, sharedCoords?.lon, resolveFromFix])

  return { ...area, status }
}
