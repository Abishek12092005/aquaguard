import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * The water AI splash — a full-screen overlay shown when the Home page opens.
 *
 * WHAT IT IS. A short, self-removing welcome: a floating water surface, the
 * wordmark, and the project's tagline, over the existing water backdrop. It
 * appears ONCE per visit to Home, holds for about two seconds so the animation
 * can actually be seen, then fades out and unmounts itself.
 *
 * WHY A TIMER AND NOT A ROUTE CHANGE. The user asked for the effect when the
 * link to Home is clicked, so it is tied to the Home page mounting, not to the
 * router. `sessionStorage` is what makes it once-per-visit rather than
 * once-per-render: React re-mounts a page on every navigation, so without it the
 * splash would replay every time the user clicked Home in the sidebar, which
 * would be an obstacle rather than a greeting.
 *
 * ACCESSIBILITY — THE PART THAT DECIDES THE SHAPE OF THIS COMPONENT:
 *
 *   `prefers-reduced-motion`  the whole overlay is skipped. A user who has asked
 *     for reduced motion gets the Home page immediately, with no animation at
 *     all. The timer is not merely shortened — nothing is shown, because a
 *     two-second blocking overlay is itself a problem for that setting.
 *   screen readers             the overlay is `aria-hidden`, so it is never
 *     announced. It carries no information the page does not already say.
 *   keyboard                  nothing is focusable inside it, so it cannot trap
 *     a keypress; the page beneath is interactive the whole time.
 *
 * The fade is a real CSS opacity transition rather than an instant unmount, so
 * the exit is as considered as the entrance.
 */

/** How long the splash is fully visible before it starts to fade. */
const HOLD_MS = 2000
/** How long the fade itself takes. */
const FADE_MS = 450

/**
 * The floating wave surface.
 *
 * Three SVG bands at different depths, each drifting sideways at its own speed
 * and phase. Opacity falls with depth, so the nearest band is the crisp one and
 * the far ones dissolve into the surface — which is what reads as water with
 * depth rather than as three stripes.
 *
 * The shapes are drawn from a sine path, and the animation is a pure `translateX`
 * over a path that is exactly one period wide, so the loop is seamless: the band
 * exits one side at the instant an identical band enters the other.
 */
function WaveBand({ y, amplitude, speed, opacity, fill }) {
  // A sine sampled across exactly one full period (2π) of the viewBox width, with
  // `preserveAspectRatio` off so the path stretches to fill. The element is 200%
  // wide and holds two of these, so `translateX(-50%)` — half the element — is
  // exactly one period, which is what makes the drift loop seamlessly.
  const points = []
  const steps = 64
  for (let i = 0; i <= steps; i += 1) {
    const x = (i / steps) * 1200
    const phase = (i / steps) * Math.PI * 2
    points.push(`${x},${(y + amplitude * Math.sin(phase)).toFixed(2)}`)
  }
  const path = `M0,${y + 40} L${points.join(' L')} L1200,${y + 40} Z`

  return (
    <svg
      aria-hidden="true"
      className="absolute inset-x-0 bottom-0 h-full w-[200%]"
      viewBox="0 0 1200 120"
      preserveAspectRatio="none"
    >
      <path
        d={path}
        fill={fill}
        opacity={opacity}
        style={{
          animation: `splash-wave-drift ${speed}s linear infinite`,
        }}
      />
    </svg>
  )
}

/**
 * The splash overlay.
 *
 * Returns `null` unless it should be on screen, so a dismissed splash costs no
 * DOM at all rather than being hidden with a class.
 */
export default function WaterSplash() {
  const [visible, setVisible] = useState(false)
  const [leaving, setLeaving] = useState(false)
  // Whether this component instance has already made the show-or-not decision.
  // It is what makes the StrictMode remount a no-op for the effect above.
  const ownsRef = useRef(false)

  // SHOWING AND DISMISSING ARE TWO EFFECTS, AND THAT SPLIT IS THE WHOLE FIX.
  //
  // WHAT WENT WRONG, and it took three attempts and a browser to see it. React
  // 18's StrictMode (main.jsx) mounts, unmounts and remounts every component once
  // in development. The first version decided visibility AND scheduled the exit
  // timers in one effect, gated on a sessionStorage flag:
  //
  //   run 1   flag unset -> show the splash, WRITE the flag, schedule timers
  //   cleanup  StrictMode's simulated unmount CANCELS those timers
  //   run 2   flag now set -> "already shown", return early, schedule NOTHING
  //
  // `visible` was still true, so a full-screen overlay covered the Home page with
  // nothing left to ever remove it.
  //
  // The obvious repair — a ref recording that the instance already handled it —
  // made it strictly WORSE, and only the browser proved it: the overlay was still
  // there at 3.8 s, fully opaque, `data-state="shown"`. The ref suppressed
  // scheduling on the remount, so the cancelled timers were never re-created and
  // `visible` was never reset. Every later click on Home would show it stuck again.
  //
  // THE FIX, and the reason it holds. The two jobs go in two effects with two
  // different dependencies, and the ORDER in which they first run is the whole
  // mechanism:
  //
  //   effect 1  []           decides WHETHER to show. On a StrictMode remount
  //                           `ownsRef` is already true, so it does nothing at
  //                           all — no state change, no flag rewrite.
  //   effect 2  [visible]    schedules the exit. On the StrictMode remount
  //                           `visible` has NOT changed yet, so this effect does
  //                           not re-run and nothing is cancelled or duplicated.
  //
  // Effect 1 runs twice, both times with `visible === false` — `setVisible(true)`
  // from the first pass has not been committed yet, and the second pass returns
  // early. Effect 2 therefore runs exactly ONCE in total, after `visible` is
  // genuinely true, and owns the timers for the rest of the splash's life. A
  // normal cleanup on it is correct and is what stops the timers if the user
  // navigates away mid-splash.
  useEffect(() => {
    const prefersReducedMotion =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (prefersReducedMotion) return

    // A StrictMode remount of this same instance: the decision is already made and
    // `visible` already holds it, so the correct action is to do nothing.
    if (ownsRef.current) return
    ownsRef.current = true

    let alreadyShown = false
    try {
      alreadyShown = window.sessionStorage?.getItem('aquaguard.splashShown') === '1'
    } catch {
      // A blocked storage API (private mode, strict settings) must not break the
      // page: the worst case is that the splash replays, which is harmless.
    }

    if (alreadyShown) return

    setVisible(true)
    try {
      window.sessionStorage?.setItem('aquaguard.splashShown', '1')
    } catch {
      // As above - ignored on purpose.
    }
  }, [])

  // The dismissal, armed only once the splash is genuinely on screen. A normal
  // cleanup, which is right: it fires when the user navigates away mid-splash
  // (the component really is going away then) and does not fire on the StrictMode
  // remount above, because `visible` never changed.
  useEffect(() => {
    if (!visible) return undefined

    const holdTimer = window.setTimeout(() => setLeaving(true), HOLD_MS)
    const closeTimer = window.setTimeout(() => setVisible(false), HOLD_MS + FADE_MS)

    return () => {
      window.clearTimeout(holdTimer)
      window.clearTimeout(closeTimer)
    }
  }, [visible])


  // The three bands, memoised so the SVG paths are not rebuilt on every render.
  const bands = useMemo(
    () => [
      { y: 44, amplitude: 7, speed: 9, opacity: 0.55, fill: 'rgb(56 189 248 / 0.55)' },
      { y: 62, amplitude: 6, speed: 13, opacity: 0.4, fill: 'rgb(14 165 233 / 0.5)' },
      { y: 80, amplitude: 5, speed: 18, opacity: 0.28, fill: 'rgb(2 132 199 / 0.45)' },
    ],
    [],
  )

  if (!visible) return null

  return (
    <div
      aria-hidden="true"
      // A stable hook for tests. The overlay carries no accessible name by
      // design (it is aria-hidden decoration), so without this there is no
      // reliable way to assert its presence and absence from the outside.
      data-testid="water-splash"
      data-state={leaving ? 'leaving' : 'shown'}
      className={`pointer-events-none fixed inset-0 z-[100] flex flex-col items-center justify-center bg-gradient-to-b from-slate-950 via-blue-950 to-cyan-950 transition-opacity duration-500 ${leaving ? 'opacity-0' : 'opacity-100'
        }`}
    >
      {/* THE WATER. Three bands at different depths, drifting at different
          speeds, so the surface never looks like one repeating strip. */}
      <div className="absolute inset-x-0 bottom-0 h-1/2">
        {bands.map((band) => (
          <WaveBand key={band.y} {...band} />
        ))}
      </div>

      {/* A soft glow above the water line, standing in for light on the surface. */}
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-64 w-64 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan-400/20 blur-3xl" />

      {/* THE WORDMARK. Centred, and the only text in the overlay. */}
      <div className="relative flex flex-col items-center gap-3 px-6 text-center">
        <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-cyan-400/15 text-cyan-300 ring-1 ring-cyan-300/30">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-9 w-9"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 3c4 5 6 8 6 11a6 6 0 0 1-12 0c0-3 2-6 6-11Z" />
          </svg>
        </span>

        <h2 className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">
          AquaGuard AI
        </h2>
        <p className="max-w-sm text-sm text-cyan-100/70">
          AI-Based Water Quality Monitoring &amp; Prediction
        </p>

        {/* A determinate-looking progress hint, so the two seconds do not read
            as a hang. It is purely decorative and carries no meaning. */}
        <span className="mt-2 block h-1 w-32 overflow-hidden rounded-full bg-white/10">
          <span className="block h-full w-1/3 rounded-full bg-cyan-300/70 motion-safe:animate-[splash-shimmer_1.1s_ease-in-out_infinite]" />
        </span>
      </div>
    </div>
  )
}
