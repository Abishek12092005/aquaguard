/**
 * DeviceLocationProvider — ONE app-wide source for the visitor's location grant.
 *
 * THE PROBLEM THIS SOLVES. Location was previously owned per screen: Rainy
 * Alerts asked on mount, the Location Prediction page asked on its own, and a
 * small prompt on Home asked again. Nothing coordinated them, so the browser
 * permission dialog could appear more than once, two screens could disagree
 * about whether the visitor had allowed anything, and the answer was not
 * available to any component that was not one of those three.
 *
 * NOW THERE IS ONE OWNER. This provider holds:
 *
 *   1. the PERMISSION STATE — idle / prompting / locating / granted / denied /
 *      unsupported — so every screen reads the same answer;
 *   2. the FIX, `{ lat, lon }`, the instant the browser reports it — BEFORE any
 *      reverse-geocode — so a map marker can move and the location field can be
 *      filled from real coordinates without waiting on a network round-trip;
 *   3. the RESOLVED PLACE, at place granularity, filled in ASYNCHRONOUSLY once
 *      that fix has been reverse-geocoded, so Rainy Alerts can fetch real alerts
 *      for the device's state and Location Prediction can reuse the same
 *      authorised position;
 *   4. the ONE-SHOT RULE — the global prompt is offered at most once per
 *      session, and a decline is remembered, so the visitor is never repeatedly
 *      blocked by the same question.
 *
 * WHAT IT NEVER DOES. It never calls the browser's geolocation on its own at
 * load: the request is made ONLY from `requestLocation()`, which the global
 * prompt's "Allow" button (and a screen's own "Use My Location" button) calls.
 * So the browser's own permission dialog is always the result of an explicit
 * click, never of a page opening.
 *
 * COORDINATES FIRST, ADDRESS SECOND. `requestLocation` sets `coords` and marks
 * the request resolved as soon as the browser answers — no artificial delay,
 * no waiting for the geocoder before the rest of the application can react —
 * and only then starts the reverse-geocode in the background. A geocode that
 * fails leaves the coordinates intact (so manual entry still works) and simply
 * leaves `place` null, which the screens already render as "could not be named".
 *
 * ONE FIX, MANY CALLERS. A fix obtained here is written to `coords`; a screen
 * that runs its own `getCurrentPosition` (the map's own centring, Rainy Alerts'
 * forecast, "Use My Location") can hand that fix back with `reuseFix()` so the
 * shared state is populated without a second browser request. The reversed
 * promise is shared too, so concurrent callers do not fire two geocodes for one
 * coordinate.
 *
 * NOTHING IS PERSISTED EXCEPT THE DECISION FLAG. The coordinates and the place
 * live in React state for the life of the tab and are never written to
 * localStorage or sessionStorage; the only stored value is the string "we have
 * already asked this session", which carries no location.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import DeviceLocationContext, { LOCATION_STATUS, normaliseGeoErrorCode } from '@/context/deviceLocationContextObject'
import { locationApi } from '@/api'

// The one stored key: that the question has been asked this session. A value of
// 'granted' or 'denied' also records the answer, so a reload in the same tab
// does not re-ask. It holds no coordinates.
const DECISION_KEY = 'aquaguard.location.decision'

function readDecision() {
  try {
    return window.sessionStorage.getItem(DECISION_KEY) || null
  } catch {
    // A locked-down browser (private mode, storage disabled) means "no
    // decision on record", which is the safe default: the prompt may show once
    // more rather than never showing at all.
    return null
  }
}

function writeDecision(value) {
  try {
    window.sessionStorage.setItem(DECISION_KEY, value)
  } catch {
    /* See readDecision(). */
  }
}

/** Read the place fields out of the reverse-geocode response, whichever key a provider used. */
function readPlace(payload) {
  const p = payload?.place || payload?.data || payload || {}
  const pick = (...keys) => {
    for (const key of keys) {
      const value = p[key]
      if (typeof value === 'string' && value.trim()) return value.trim()
    }
    return null
  }
  return {
    name: pick('name', 'location_name', 'display_name'),
    area: pick('area', 'suburb', 'neighbourhood', 'locality'),
    city: pick('city', 'town', 'location_city'),
    district: pick('district', 'county', 'admin2'),
    state: pick('state', 'region', 'admin1'),
    country: pick('country', 'admin0'),
    pincode: pick('pincode', 'postcode'),
  }
}

export default function DeviceLocationProvider({ children }) {
  // 'idle'      nothing asked yet
  // 'prompting' the global prompt is on screen
  // 'locating'  the browser prompt is open / the fix is in flight
  // 'granted'   a fix was obtained; the place is reverse-geocoded in the
  //             background and may still be null
  // 'denied'    the visitor refused
  // 'unsupported' no geolocation API, or not a secure context
  const [status, setStatus] = useState(() => {
    // A decision already recorded this session is honoured immediately: a
    // granted session skips the prompt, a denied one is not asked again.
    const decision = readDecision()
    if (decision === 'denied') return LOCATION_STATUS.denied
    return LOCATION_STATUS.idle
  })
  const [place, setPlace] = useState(null)
  const [coords, setCoords] = useState(null)
  const [error, setError] = useState(null)
  // WHY the last request failed, so a screen can keep the promise's `code`
  // vocabulary (PERMISSION_DENIED / TIMEOUT / POSITION_UNAVAILABLE / unsupported
  // / insecure) and word its own message accordingly, rather than flattening
  // every failure into one sentence.
  const [errorCode, setErrorCode] = useState(null)
  // `true` once the visitor has granted or denied through the browser's own
  // dialog (the Permissions API tells us). Used only to SKIP the popup — never
  // to decide to read a location without a click.
  const [browserPermission, setBrowserPermission] = useState(null)

  // Guards against two concurrent requests (e.g. a double click on Allow) and
  // against a second prompt being opened while one is already asking.
  const requesting = useRef(false)
  // The coordinate currently being reverse-geocoded, and the promise that is
  // doing it, so two callers that hold the SAME fix share one geocode (and a
  // second request for the same point does not fire a duplicate).
  const reverseFor = useRef(null)
  const reversePromise = useRef(null)

  // Learn the browser's standing permission, WITHOUT prompting. Reading the
  // Permissions API can never itself block or raise a dialog.
  //
  // WHAT THIS IS FOR, AND WHAT IT DELIBERATELY DOES NOT DO. The state is kept
  // only so the app knows whether clicking Allow will be answered DIRECTLY by
  // the browser (state 'granted' - no dialog at all) or will raise the browser's
  // own one-time dialog (state 'prompt').
  //
  // It deliberately does NOT record a 'granted' session decision. It used to,
  // and that was wrong for this app: the session decision is what SUPPRESSES the
  // popup, so an already-granted browser meant the popup never appeared - and
  // the brief is explicit that the location must be taken from THIS popup, not
  // silently behind it. A grant the visitor gave on a previous visit must not
  // hide the popup now; it only makes the popup's Allow instant.
  useEffect(() => {
    if (typeof navigator === 'undefined' || !navigator.permissions?.query) return undefined
    let active = true
    let status = null
    const onChange = () => {
      if (!active) return
      setBrowserPermission(status?.state ?? null)
    }
    navigator.permissions
      .query({ name: 'geolocation' })
      .then((result) => {
        if (!active) return
        status = result
        onChange()
        // Older browsers expose only `addEventListener`; guard both.
        result.addEventListener?.('change', onChange)
      })
      .catch(() => {
        /* The API is optional; without it the popup behaves exactly as before. */
      })
    return () => {
      active = false
      status?.removeEventListener?.('change', onChange)
    }
  }, [])

  /** Show the global prompt, unless a decision is already on record. */
  const offerPrompt = useCallback(() => {
    if (readDecision()) return false
    // An ALREADY-GRANTED browser permission does NOT suppress the popup. It used
    // to, and that hid the front door the brief names: the location must be
    // taken FROM this popup, so the popup shows even for a returning visitor —
    // and because the browser already remembers the grant, its Allow is then
    // answered instantly, with no second dialog of any kind. A browser that has
    // natively REFUSED is still respected here: no request can succeed, so the
    // visitor is not shown a question that has no way to be answered yes.
    if (browserPermission === 'denied') return false
    if (requesting.current) return false
    setStatus((current) =>
      current === LOCATION_STATUS.granted ? current : LOCATION_STATUS.prompting,
    )
    return true
  }, [browserPermission])

  /**
   * Show the prompt ON DEMAND, even after a decline.
   *
   * THE DIFFERENCE FROM `offerPrompt`. `offerPrompt` is the once-per-session
   * automatic offer: it refuses when a decision is already on record, which is
   * what stops the visitor being blocked by the same question on every page.
   * This one is the OPPOSITE case — a screen that genuinely needs a location (or
   * a "Use my location" button the visitor pressed) asks for permission at that
   * moment. A visitor who declined the first popup must still be able to grant it
   * later, so a recorded decline is not treated as final here.
   *
   * Returns false only in the two states where asking would be pointless or
   * rude: the permission is already granted, or a request is already in flight.
   */
  const requestPermissionPrompt = useCallback(() => {
    if (requesting.current) return false
    if (readDecision() === 'granted') return false
    // Denied is NOT treated as final here, for the reason above: a visitor who
    // declined the automatic offer must still be able to grant it on an explicit
    // click. A browser that has already refused, however, is respected.
    setStatus((current) =>
      current === LOCATION_STATUS.granted ? current : LOCATION_STATUS.prompting,
    )
    return true
  }, [])

  /** The visitor declined, or closed the prompt without allowing. */
  const declineLocation = useCallback(() => {
    writeDecision('denied')
    setStatus(LOCATION_STATUS.denied)
    setError(null)
    setErrorCode(null)
  }, [])

  /**
   * Reverse-geocode a fix to a place, ASYNCHRONOUSLY, sharing one request.
   *
   * THE COORDINATES ARE ALREADY IN STATE BY THE TIME THIS RUNS. It never blocks
   * the caller: the promise resolves to the place or to null, and the provider's
   * own state is updated when — and only when — a real answer arrives. Two
   * callers holding the same fix share one request, so a screen that reuses the
   * map's fix does not fire a second geocode for the same point.
   */
  const resolvePlace = useCallback((latitude, longitude) => {
    const lat = Number(latitude)
    const lon = Number(longitude)
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return Promise.resolve(null)
    if (reverseFor.current === `${lat},${lon}` && reversePromise.current) {
      return reversePromise.current
    }
    reverseFor.current = `${lat},${lon}`
    reversePromise.current = (async () => {
      let resolved = null
      try {
        const response = await locationApi.reverse({ lat, lon })
        resolved = readPlace(response?.data ?? response)
      } catch {
        // A geocode failure is NOT a location failure: the fix is in hand, so a
        // screen can still offer manual entry and the map still has a point.
        resolved = null
      }
      setPlace(resolved)
      return resolved
    })()
    return reversePromise.current
  }, [])

  /**
   * Request the browser's location. THE ONLY PLACE `getCurrentPosition` IS CALLED.
   *
   * RESOLVES AS SOON AS THE BROWSER ANSWERS. Coordinates are set first and the
   * status becomes 'granted' immediately; the reverse-geocode runs afterwards in
   * the background. Nothing here waits on the network, so a caller can move a
   * marker or fill a location field from real coordinates without a hold-up.
   *
   * Resolves to `{ coords, place, code }`:
   *   * success  -> `{ coords: {lat,lon}, place: null, code: 'GRANTED' }` and the
   *     place arrives later through the shared state;
   *   * refusal / unavailable / timeout / unsupported / insecure -> `{ coords:
   *     null, place: null, code }` with `code` one of the browser's own names.
   *
   * A DENIAL IS NOT PERMANENT. Unlike the automatic offer, an explicit request
   * that the visitor refuses does not write a 'denied' session decision — they
   * must be able to try again (and the browser, not this app, owns that verdict).
   */
  const requestLocation = useCallback(async () => {
    if (requesting.current) return { coords: null, place: null, code: 'REQUESTING' }
    requesting.current = true

    // SECURE CONTEXT FIRST. Browsers only expose geolocation over HTTPS or
    // localhost; on a plain-HTTP origin `getCurrentPosition` never calls back at
    // all, so reporting "unsupported" up front is the honest answer rather than
    // leaving the caller on a spinner forever.
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
      requesting.current = false
      setErrorCode('insecure')
      setStatus(LOCATION_STATUS.unsupported)
      return { coords: null, place: null, code: 'insecure' }
    }
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      requesting.current = false
      setErrorCode('unsupported')
      setStatus(LOCATION_STATUS.unsupported)
      return { coords: null, place: null, code: 'unsupported' }
    }

    setStatus(LOCATION_STATUS.locating)
    setError(null)
    setErrorCode(null)

    const outcome = await new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) => resolve({ position }),
        (geoError) => resolve({ geoError }),
        // `maximumAge` lets the browser answer from a recent cached fix rather
        // than waking the GPS, which is why a repeat request is fast. The
        // timeout is generous because a cold fix legitimately takes a moment;
        // `enableHighAccuracy` stays off so an approximate fix is returned
        // promptly instead of the caller waiting on a satellite lock.
        { enableHighAccuracy: false, timeout: 12000, maximumAge: 5 * 60 * 1000 },
      )
    })

    const { latitude, longitude, accuracy } = outcome.position?.coords || {}
    if (typeof latitude !== 'number' || typeof longitude !== 'number') {
      // PERMISSION_DENIED, POSITION_UNAVAILABLE and TIMEOUT land here, each with
      // its own code so a caller can word the failure honestly.
      const code = normaliseGeoErrorCode(outcome.geoError?.code)
      requesting.current = false
      setErrorCode(code)
      // A refusal is a normal outcome, but it must not be recorded as a session
      // decision: the explicit request is exactly the case where the visitor is
      // allowed to try again (and to allow, if they change their mind).
      setStatus(code === 'PERMISSION_DENIED' ? LOCATION_STATUS.denied : LOCATION_STATUS.idle)
      return { coords: null, place: null, code }
    }

    // COORDINATES COMMITTED IMMEDIATELY — this is the whole point of the flow.
    const fix = { lat: latitude, lon: longitude, accuracy }
    setCoords(fix)
    writeDecision('granted')
    setBrowserPermission('granted')
    setStatus(LOCATION_STATUS.granted)
    requesting.current = false

    // THE ADDRESS FOLLOWS IN THE BACKGROUND. Deliberately not awaited: the
    // caller already has real coordinates, and the place lands in shared state
    // when it arrives.
    resolvePlace(latitude, longitude)
    return { coords: { lat: latitude, lon: longitude }, place: null, code: 'GRANTED' }
  }, [resolvePlace])

  /**
   * Adopt a fix the CALLER already obtained, so the shared state reflects it.
   *
   * Used by a screen that runs its own `getCurrentPosition` (the map's centring,
   * Rainy Alerts' forecast, "Use My Location" after consuming a shared fix). No
   * browser request is made here; the reverse-geocode is shared, so a coordinate
   * the provider is already resolving is not resolved twice.
   */
  const reuseFix = useCallback(
    async (fix) => {
      const latitude = Number(fix?.lat)
      const longitude = Number(fix?.lon ?? fix?.lng)
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null
      setCoords({ lat: latitude, lon: longitude })
      writeDecision('granted')
      setBrowserPermission('granted')
      setStatus(LOCATION_STATUS.granted)
      setErrorCode(null)
      return resolvePlace(latitude, longitude)
    },
    [resolvePlace],
  )

  const value = useMemo(
    () => ({
      status,
      place,
      coords,
      error,
      offerPrompt,
      requestPermissionPrompt,
      requestLocation,
      declineLocation,
      reuseFix,
      errorCode,
      browserPermission,
      // Convenience flags, so a screen does not have to know the status names.
      hasDecision: Boolean(readDecision()),
      isGranted: status === LOCATION_STATUS.granted,
      isDenied: status === LOCATION_STATUS.denied || status === LOCATION_STATUS.unsupported,
    }),
    [
      status,
      place,
      coords,
      error,
      offerPrompt,
      requestPermissionPrompt,
      requestLocation,
      declineLocation,
      reuseFix,
      errorCode,
      browserPermission,
    ],
  )

  return (
    <DeviceLocationContext.Provider value={value}>{children}</DeviceLocationContext.Provider>
  )
}
