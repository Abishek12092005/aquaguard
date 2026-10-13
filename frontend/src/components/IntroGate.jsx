import { lazy, Suspense, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import { ROUTES } from '@/utils/constants'

/**
 * The application's entry gate.
 *
 * PROMPT 14: the sea-water intro plays ONCE, when the site is opened, and then
 * the normal application takes over. This component owns that decision and
 * renders no markup of its own, so it cannot affect layout.
 *
 * WHY THE REAL APPLICATION IS ALIVE BEHIND THE OVERLAY (requirement 12). The
 * children — the actual router and pages — are rendered immediately and the
 * intro is layered on top. So the application initialises normally while the
 * animation plays, its data requests fire immediately, and a genuine error in
 * the Home page is rendered and becomes visible the moment the overlay clears.
 *
 * That is the whole reason this is an OVERLAY rather than a gate that withholds
 * `children` until a timer finishes. A gate would delay real application
 * initialisation behind a decorative animation, and would hide a real error
 * behind it for three seconds. An overlay does neither.
 */
const SeaIntro = lazy(() => import('@/components/SeaIntro'))

/** The sessionStorage key marking the intro as already played. */
const SEEN_KEY = 'aquaguard.intro.seen'

/**
 * Whether the intro should play, or `false` if it should not.
 *
 * TWO INDEPENDENT CONDITIONS, and both matter:
 *
 *   1. ENTRY POINT ONLY (requirement 10). The animation belongs to *opening the
 *      site*. A visitor who opens the site directly on `/dashboard`, or who
 *      refreshes an internal route, is not opening it, and must not be made to
 *      sit through an animation they have already seen. `/` is included because
 *      the root redirects to Home — that redirect IS the entry point, not a
 *      separate destination.
 *
 *   2. ONCE PER BROAD SESSION. Component state alone would only survive a
 *      remount within one page load, so a browser refresh would replay the
 *      intro. `sessionStorage` lasts exactly as long as the tab, which is the
 *      scope the brief asks for: it dies with the tab and re-arms for the next
 *      visit.
 *
 * A storage failure (private mode, locked-down browser) is treated as "show it".
 * The cost is one unexpected animation; the alternative — silently never showing
 * the feature — is worse for the requirement it exists to satisfy.
 */
function shouldShowIntro() {
  if (typeof window === 'undefined') return false

  const path = window.location.pathname
  const isEntryPoint = path === '/' || path === ROUTES.home
  if (!isEntryPoint) return false

  try {
    if (window.sessionStorage.getItem(SEEN_KEY)) return false
    // Marked HERE, at the decision, rather than by the component once it has
    // animated: a visitor who navigates away mid-intro has still opened the
    // site, and should not get it again on the way back.
    window.sessionStorage.setItem(SEEN_KEY, '1')
    return true
  } catch {
    return true
  }
}

export default function IntroGate({ children }) {
  // Computed once, during the first render, from the URL and the session flag.
  // Deliberately NOT done in an effect: an effect would render the application
  // first and pop the overlay in a frame later, which reads as a flash rather
  // than as an intro.
  const [show] = useState(shouldShowIntro)

  // `document` does not exist during the server render / test render, and the
  // portal is only mounted after mount anyway (see below), so this is null
  // until then.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  return (
    <>
      {/*
        THE PORTAL IS LOAD-BEARING, and it is not decoration.

        Rendered in place, the overlay is a `position: fixed` element INSIDE the
        application's own tree. Its `z-index` is then only meaningful within its
        nearest stacking context, and the pages render `position: relative`
        elements with their own stacking contexts — so the shell painted over the
        intro while the intro still measured as present, full-size and opaque in
        the DOM. Nothing was wrong with the overlay; it was simply competing
        inside someone else's context.

        Portalling to `document.body` puts it beside the application rather than
        inside it, where its z-index is compared against the whole document. That
        makes the overlay immune to any stacking context the pages happen to
        create now or in future, which is the only version of "it works today"
        worth having.
      */}
      {mounted &&
        show &&
        createPortal(
          <Suspense fallback={null}>
            <SeaIntro />
          </Suspense>,
          document.body,
        )}
      {children}
    </>
  )
}