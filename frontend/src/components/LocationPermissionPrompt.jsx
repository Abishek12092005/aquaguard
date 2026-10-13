import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import Button from '@/components/Button'
import Icon from '@/components/Icon'
import LocationPinIcon from '@/components/LocationPinIcon'
import { ICONS } from '@/config/navigation'
import { LOCATION_STATUS } from '@/context/deviceLocationContextObject'
import useDeviceLocation from '@/context/useDeviceLocation'

/**
 * THE GLOBAL LOCATION-PERMISSION POPUP.
 *
 * Shown AUTOMATICALLY once per session, about two seconds after the app first
 * loads, and it appears on WHATEVER PAGE THE VISITOR IS ON — it is mounted by
 * the SHELL, not by any single screen, so navigating during the two-second wait
 * cannot prevent it and it is never mounted twice.
 *
 * IT IS A DECISION, NOT A PARAGRAPH. It asks directly, centered in the viewport,
 * with the page behind it blurred and non-interactive until the visitor answers:
 *
 *   * CENTERED AND RESPONSIVE. `fixed inset-0 flex items-center justify-center`
 *     centers the dialog at every viewport size; the dialog is `max-w-md` with
 *     `p-4` on the overlay and a max height with internal scroll, so a phone
 *     keeps a margin and a short screen can still reach both buttons.
 *   * THE BACKGROUND IS BLURRED AND BLOCKED. The overlay dims and blurs the page
 *     (`backdrop-blur-sm`), swallows every pointer event, and a capture-phase
 *     `keydown` listener stops keyboard interaction reaching the page below.
 *     Body scroll is locked meanwhile. There is deliberately NO click-to-dismiss
 *     on the backdrop: the only ways out are the two buttons.
 *   * ALLOW and DECLINE are the only controls. "Allow" calls the REAL
 *     `navigator.geolocation.getCurrentPosition` through the shared provider and
 *     keeps the popup open with a spinner UNTIL THE BROWSER ACTUALLY ANSWERS, so
 *     permission is never marked granted before a location is real. The moment a
 *     fix lands the popup closes — coordinates are written to shared state
 *     immediately and the address is reverse-geocoded afterwards, off the
 *     critical path. "Decline" records a denied decision for the session and
 *     closes immediately.
 *
 * FAILURES ARE WORDED HONESTLY, ONE BY ONE. A refusal, a timeout, a device with
 * no GPS fix, a browser with no geolocation at all and an insecure origin
 * (plain HTTP) are five different problems, and the popup says which one
 * happened — then stays open so the visitor can read it, try again, or decline
 * and type a place by hand. The coordinates are never invented to fill the gap.
 *
 * THE ONE-SHOT RULE LIVES IN THE PROVIDER. `offerPrompt()` refuses when a
 * decision is already on record (or the browser itself reports the permission
 * already answered), so this can never appear a second time in the same session
 * — which is what stops the visitor being repeatedly blocked.
 */

/** Roughly two seconds after the app is available. */
const DELAY_MS = 2000

/** One sentence per failure, so a refusal never reads as "unavailable". */
const FAILURE_MESSAGE = {
  PERMISSION_DENIED:
    'Location permission was refused. You can still search for a place by name above.',
  TIMEOUT:
    'Finding your location took too long. Try again somewhere with a clearer view of the sky, or search manually.',
  POSITION_UNAVAILABLE:
    'Your device could not work out its position right now. Make sure location services are switched on, then try again — or search manually.',
  insecure:
    'This page is not loaded over a secure connection (HTTPS), and browsers only share a location over HTTPS. Open AquaGuard AI over HTTPS, or search manually.',
  unsupported:
    'This browser cannot report a location. Please search for a place by name instead.',
}

// Re-entrant body-scroll lock, shared in spirit with RainPermissionModal so two
// overlays never release each other's lock.
let openPopupCount = 0

export default function LocationPermissionPrompt() {
  const location = useDeviceLocation()
  const status = location?.status

  // Start the two-second timer once, on mount. Whether the popup is ALLOWED to
  // appear is decided by the provider when the timer fires (a decision recorded
  // meanwhile is honoured), not at mount.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      location?.offerPrompt()
    }, DELAY_MS)
    return () => window.clearTimeout(timer)
    // Intentionally once per mount: `offerPrompt` is stable, and re-running this
    // on every provider render would restart the timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // THE REASON FOR A FAILED ATTEMPT, held here rather than derived from status
  // alone so the popup can distinguish "refused" from "timed out" from "no fix"
  // and from "no GPS at all". It is cleared whenever a fresh attempt starts.
  const [failure, setFailure] = useState(null)

  // SET THE MOMENT ALLOW IS PRESSED, and it is what makes the popup GO AWAY
  // IMMEDIATELY. The brief is explicit: granting access should dismiss the popup
  // at once, with no lingering "load aagitu irukku" state. The request itself
  // keeps running invisibly behind the page; this only decides whether the
  // DIALOG is still on screen.
  //
  // It is deliberately a SEPARATE flag from `requesting`: the popup's visibility
  // must not be tied to the request's lifetime, or the popup would stay up for
  // as long as the browser takes to answer.
  const [dismissed, setDismissed] = useState(false)

  // THE POPUP IS OPEN while the provider says it is prompting, OR while there is
  // a failure to explain — AND only until the visitor dismisses it by pressing
  // Allow. Once Allow is pressed the popup is gone immediately, even though the
  // underlying request is still in flight, so there is no lingering loading
  // dialog.
  //
  // THE FAILURE TERM IS LOAD-BEARING. After a refusal/timeout the provider moves
  // to `denied` or `idle`, which is NOT `prompting`/`locating`: without this term
  // the popup would close silently on failure and the visitor would be told
  // nothing — the exact "nothing happened" experience that makes them press
  // Allow repeatedly. A recorded failure keeps the dialog on screen to explain
  // itself; dismissing it (Allow again, or Decline) clears it.
  const open =
    !dismissed &&
    (status === LOCATION_STATUS.prompting ||
      status === LOCATION_STATUS.locating ||
      Boolean(failure))
  // The in-dialog spinner. It can only ever show in the single frame between the
  // prompt appearing and Allow being pressed — there is deliberately no loading
  // screen that outlives the dismissal.
  const requesting = status === LOCATION_STATUS.locating && !dismissed

  /**
   * THE ONE CLICK THAT ASKS THE BROWSER. Laid out deliberately so nothing is
   * awaited before the permission dialog can appear:
   *
   *   1. clear the previous failure — a stale "timed out" must not sit there;
   *   2. DISMISS THE POPUP AT ONCE, so it is gone the moment the visitor presses
   *      Allow — no visible loading screen, no popup hanging around while the
   *      fix resolves;
   *   3. fire the real request and let it run INVISIBLY behind the page;
   *   4. if it FAILS, re-show the popup with the exact reason, so the visitor can
   *      read it and try again. Success needs nothing: the coordinates are in
   *      shared state and the popup is already gone.
   *
   * A failure must NOT be swallowed: a silent "nothing happened" after pressing
   * Allow is exactly what makes a user press it again and again. So the popup
   * comes back with the reason, and only when there is genuinely nothing to say
   * (a granted fix) does it stay closed.
   */
  async function allow() {
    setFailure(null)
    // GO AWAY NOW. The inline spinner is skipped entirely for the success path.
    setDismissed(true)
    const outcome = await location?.requestLocation?.()
    if (!outcome || outcome.code === 'GRANTED' || outcome.coords) {
      // Granted (or in flight): stay closed. The address resolves in the
      // background; nothing about it belongs on this popup.
      return
    }
    // Refused / timed out / unavailable / unsupported / insecure: bring the
    // popup back with the honest reason and let the visitor retry or decline.
    setFailure(FAILURE_MESSAGE[outcome.code] || FAILURE_MESSAGE.POSITION_UNAVAILABLE)
    setDismissed(false)
  }

  // Lock background scrolling while the popup is open.
  useEffect(() => {
    if (!open) return undefined
    openPopupCount += 1
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      openPopupCount -= 1
      if (openPopupCount === 0) document.body.style.overflow = previous
    }
  }, [open])

  // Block keyboard interaction with the page below while the popup is open.
  useEffect(() => {
    if (!open) return undefined
    const block = (event) => event.stopPropagation()
    window.addEventListener('keydown', block, true)
    return () => window.removeEventListener('keydown', block, true)
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      role="presentation"
      // NO onClick: the brief is explicit that the background must not dismiss
      // this. The overlay exists to be clicked into, not through.
      data-testid="location-permission-popup"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="location-permission-title"
        aria-describedby="location-permission-body"
        className="max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto rounded-card bg-white p-6 shadow-xl dark:bg-slate-800"
      >
        <div className="flex items-start gap-3">
          <span
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-aqua-50 text-aqua-600 dark:bg-aqua-900 dark:text-aqua-300"
            aria-hidden="true"
          >
            <LocationPinIcon className="h-5 w-5" animated={false} />
          </span>
          <div className="min-w-0">
            <h2
              id="location-permission-title"
              className="text-lg font-semibold tracking-tight text-slate-900 dark:text-white"
            >
              Use your location?
            </h2>
            <p
              id="location-permission-body"
              className="mt-1 text-sm text-slate-600 dark:text-slate-300"
            >
              This only asks your browser for location permission. You can allow
              it now and still enter any place by hand on every screen — allowing
              here starts nothing on its own. The position is used only to find
              your area, and it is never stored.
            </p>
          </div>
        </div>

        {/* The visible difference between "asking" and "asked". The spinner is
            the ONLY loading indicator here, and it is up only while the browser
            is genuinely deciding — the request's own pending window. */}
        {requesting ? (
          <div className="mt-5 flex items-center gap-3 rounded-field bg-slate-50 px-4 py-3 dark:bg-slate-900/60">
            <span
              className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-aqua-500 border-t-transparent"
              aria-hidden="true"
            />
            <p className="text-sm text-slate-600 dark:text-slate-300">
              Waiting for your browser&rsquo;s answer…
            </p>
          </div>
        ) : null}

        {/* WHY THE LAST ATTEMPT DID NOT PRODUCE A POSITION. One sentence per
            cause — a refusal is told apart from a timeout, an unavailable GPS
            and an insecure origin — and the popup stays open so it can be read,
            retried, or declined. `role="alert"` announces it without stealing
            focus from the Allow button. */}
        {!requesting && failure ? (
          <div
            role="alert"
            data-testid="location-permission-error"
            className="mt-5 flex items-start gap-3 rounded-field border border-caution-light bg-caution-light/40 px-4 py-3 text-sm text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
          >
            <span className="mt-0.5 shrink-0 text-caution-dark" aria-hidden="true">
              <Icon path={ICONS.info} className="h-4 w-4" />
            </span>
            <p>{failure}</p>
          </div>
        ) : null}

        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="secondary"
            onClick={() => location?.declineLocation()}
            disabled={requesting}
            data-testid="location-permission-decline"
          >
            Decline
          </Button>
          <Button
            type="button"
            onClick={allow}
            loading={requesting}
            data-testid="location-permission-allow"
          >
            Allow
          </Button>
        </div>

        <p className="sr-only" role="note">
          <Icon path={ICONS.info} className="hidden" /> Choose Allow to share your
          location or Decline to continue without it.
        </p>
      </div>
    </div>,
    document.body,
  )
}
