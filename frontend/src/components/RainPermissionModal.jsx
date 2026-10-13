import { useEffect } from 'react'
import { createPortal } from 'react-dom'

import Button from '@/components/Button'
import Icon from '@/components/Icon'
import LocationPinIcon from '@/components/LocationPinIcon'
import { ICONS } from '@/config/navigation'

/**
 * THE RAINY ALERTS LOCATION PERMISSION MODAL.
 *
 * Shown when the Rainy Alerts page opens and the device location has not yet
 * been resolved. It replaces what used to be an inline intro card: a permission
 * question is a decision, not a paragraph, so it asks directly — centered in
 * the viewport, with the page behind it dimmed and blurred and every
 * interaction with that page blocked until the visitor answers.
 *
 * CENTERED AND RESPONSIVE. `fixed inset-0 flex items-center justify-center`
 * centers the dialog horizontally and vertically at every viewport size; the
 * dialog itself is `max-w-md` with `mx-4`, so on a phone it keeps a margin
 * rather than touching the screen edges.
 *
 * BLOCKING. The fixed overlay swallows clicks (it has no click-to-dismiss —
 * a permission question is not dismissed by tapping the darkness behind it),
 * and a `keydown` listener in the capture phase stops keyboard interaction
 * with the page below: Escape, Tab and Enter never reach the underlying
 * document. Background scrolling is prevented by locking `document.body`
 * overflow while the modal is open, and restored (only if this modal was the
 * one that locked it) when it closes — so a nested map picker's own lock is
 * never accidentally released.
 *
 * THE BUTTONS. "Allow" and "Decline" are the ONLY two controls, and neither
 * closes the modal until the flow they start has resolved:
 *
 *   * "Allow" calls the real `navigator.geolocation.getCurrentPosition` — the
 *     modal stays open with a spinner until the browser actually returns a
 *     fix (or an error), so permission is never *marked* granted before the
 *     location is real. The browser's own prompt is triggered by this click,
 *     by the user's choice.
 *   * "Decline" closes immediately and the page shows its honest
 *     location-denied state; the manual search box stays fully usable, so a
 *     declined visitor can still check the rain for any place they name.
 *
 * STACKING. `z-[60]`: above the topbar (z-30), the mobile sidebar backdrop
 * (z-40) and the sidebar drawer (z-50), so no page chrome can overlap it.
 * Rendered through a portal to <body>, so no ancestor's stacking context or
 * overflow rule can clip or dim it incorrectly. A module-level counter makes
 * the overflow lock re-entrant so two modals (this one and, say, the map
 * picker) never fight over `document.body`.
 */
let openModalCount = 0

export default function RainPermissionModal({ onAllow, onDecline, requesting = false }) {
  // Lock background scrolling for as long as the modal is open. Re-entrant:
  // the counter means two simultaneously open overlays each restore exactly
  // what they changed.
  useEffect(() => {
    openModalCount += 1
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      openModalCount -= 1
      if (openModalCount === 0) document.body.style.overflow = previous
    }
  }, [])

  // Block keyboard interaction with the page below. Capture phase on the
  // window, so nothing — Tab focus changes, Escape handlers, Enter on a
  // background form — reaches the underlying document while the modal asks
  // its question.
  useEffect(() => {
    const block = (event) => event.stopPropagation()
    window.addEventListener('keydown', block, true)
    return () => window.removeEventListener('keydown', block, true)
  }, [])

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      role="presentation"
    // No onClick: the brief is explicit that clicking the background must
    // NOT dismiss the modal. The overlay exists to be clicked *into*, not
    // through.
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="rain-permission-title"
        aria-describedby="rain-permission-body"
        className="w-full max-w-md rounded-card bg-white p-6 shadow-xl dark:bg-slate-800"
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
              id="rain-permission-title"
              className="text-lg font-semibold tracking-tight text-slate-900 dark:text-white"
            >
              Use your location for rain alerts
            </h2>
            <p
              id="rain-permission-body"
              className="mt-1 text-sm text-slate-600 dark:text-slate-300"
            >
              Rainy Alerts reads the forecast for the state your device is in.
              Your browser will ask for permission first — the position is used
              to find that state and is never stored.
            </p>
          </div>
        </div>

        {/* THE STATE LINE. While "Allow" is waiting on the browser, the modal
            says so rather than silently doing nothing — the spinner is the
            visible difference between "asking" and "asked". */}
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

        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="secondary"
            onClick={onDecline}
            disabled={requesting}
          >
            Decline
          </Button>
          <Button type="button" onClick={onAllow} loading={requesting}>
            Allow
          </Button>
        </div>

        {/* Screen-reader-only hint about the two buttons being the only way
            out, for parity with the visual layout. */}
        <p className="sr-only" role="note">
          <Icon path={ICONS.info} className="hidden" /> Choose Allow to share
          your location or Decline to continue without it.
        </p>
      </div>
    </div>,
    document.body,
  )
}
