import { useEffect, useState } from 'react'

/**
 * SeaIntro — the opening animation shown once when the application is opened.
 *
 * WHAT IT IS. A blue field with two bands of water entering from the left and
 * right screen corners, far away and small, growing toward the viewer until they
 * fill the frame edge to edge, then clearing to reveal the Home page.
 *
 * WHY THE WATER HAS NO VISIBLE LEFT/RIGHT ENDING. Each wave layer is wider than
 * the viewport (170vw) and anchored to its own bottom corner, and its SVG is
 * drawn with `preserveAspectRatio="none"` and NO fade mask, so the water reaches
 * both screen edges without a terminus anywhere. There is deliberately no
 * one-sided dissolve: that fade WAS the visible "ending point" the brief forbids,
 * because the eye can see exactly where the water stops being water. Cut off only
 * by the screen, the surface reads as a body of water running off past the frame
 * rather than as a centred graphic. The visible surface is purely the crest
 * curves, so nothing is ever centred or symmetrical as a banner.
 *
 * WHY SCALE IS THE WHOLE TRICK. The brief asks for water moving TOWARD the
 * viewer rather than sliding sideways. Sliding is a two-dimensional gesture the
 * eye reads as "flat panel moving along the screen plane"; growing is the one
 * gesture the eye reads as "distance closing". So every wave is anchored in its
 * corner and scaled from 0.12 up, and the parent carries a perspective so the
 * growth is foreshortened like a real approach rather than an even zoom.
 *
 * WHY THE WAVES ARE LAYERED INSTEAD OF DRAWN AS ONE SHAPE. A single filled path
 * that grows reads as a flat blue rectangle with a wavy top — which is what the
 * brief explicitly rules out. Three separate surfaces at different depths, each
 * with its own crest phase, produce interference between them: the boundary the
 * eye sees is never a single curve, because a second crest is always crossing
 * the first. That is what makes it read as a body of water.
 *
 * WHY THERE IS NO PROGRESS BAR AND NO NETWORK TEXT (requirement 12). Nothing
 * here is waiting for anything. The component removes itself from the tree on a
 * timer, not on a fetch resolving, and the Home page behind it is mounted and
 * fetching throughout. If the application has a genuine error, that error is
 * shown by the Home page itself and is never covered — the overlay is purely
 * decorative and is gone within three seconds.
 */

/** How long the water is on screen. Matches the `intro-*` animation durations. */
const DURATION_MS = 3000

/**
 * True once the user has asked for reduced motion (requirement 9).
 *
 * Read once at mount rather than tracked reactively: the decision is made when
 * the intro starts, and subscribing to the media query for an animation that
 * lasts three seconds would mean adding a listener purely to watch it end.
 */
function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * One wave surface.
 *
 * `phase` shifts the crest's starting point along the SVG so the two sides are
 * not the same wave rotated — otherwise the left and right fronts animate in
 * obvious mirror symmetry, which is the "flat banner" look the brief rejects.
 */
function Wave({ side, phase = 0, className = '', style }) {
  const uid = `intro-${side}-${phase}`
  return (
    <div
      className={`pointer-events-none absolute ${className}`}
      style={style}
      aria-hidden="true"
    >
      {/* THE WATER REACHES BOTH EDGES — there is deliberately NO one-sided fade.

          The previous version faded the fill to transparent toward the inward
          side (a left-to-right mask for the left wave, and its mirror for the
          right). That fade WAS the "left/right ending point" the brief forbids:
          a viewer could see exactly where the water stopped being water, which
          reads as a graphic rectangle rather than as a body of water running off
          past the screen.

          So the mask is now OPAQUE EVERYWHERE. The wave has no terminus at all: it
          is cut off only by the container's own edges, and those are pushed far
          outside the viewport (see the `w-[170vw]` layers below), so no end is
          ever on screen — on either the left, the right, or in the middle. The
          surface the eye reads is purely the crest curves.

          `preserveAspectRatio="none"` on the SVG so the single 1200-wide path
          stretches to whatever width the layer is; combined with a layer wider
          than the viewport, the crests run unbroken from off-screen to
          off-screen with no seam and no edge anywhere in frame. */}
      <svg
        viewBox="0 0 1200 700"
        preserveAspectRatio="none"
        className="h-full w-full"
      >
        <defs>
          {/* A vertical gradient for the body of the water, light at the surface
              where the light hits and deep below, which is what gives a body of
              water its volume rather than a flat fill. */}
          <linearGradient id={`${uid}-body`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.95" />
            <stop offset="45%" stopColor="#0284c7" stopOpacity="0.98" />
            <stop offset="100%" stopColor="#075985" />
          </linearGradient>
          {/* The lit lip along the crest. A gradient rather than a stroke,
              because a stroke on a scaled path scales too and reads as a wire
              rather than as light on water. */}
          <linearGradient id={`${uid}-foam`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#e0f2fe" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* --- Everything below is drawn UNDIMMED, edge to edge. --- */}
        <g>
          {/* --- The body of the water ---------------------------------------
              Closed to the bottom of the viewBox, so however this element is
              scaled or cropped the fill has no visible edge below. The only
              closing edges are the two bottom corners, which sit off-screen. */}
          <path
            d={`M0,700 L${crestCurve(phase, 430)} L1200,700 Z`}
            fill={`url(#${uid}-body)`}
          />

          {/* --- The second, nearer surface ------------------------------------
              A crest at a different phase, DEEPER in the body of the water. Where
              the two cross, the boundary the eye reads is neither curve — which
              is the interference that makes this read as moving water rather
              than one drawn line. */}
          <path
            d={`M0,700 L${crestCurve(phase + 1.6, 545)} L1200,700 Z`}
            fill="#0ea5e9"
            opacity="0.45"
          />

          {/* --- Foam on the leading crest -------------------------------------
              A CLOSED BAND traced as upper-crest-forward then lower-crest-BACK,
              not `... L${crestCurve(476)} Z`.

              WHY THAT MATTERS, and it is the fix for the visible diagonal wedge.
              The old form emitted the upper curve left-to-right, then the lower
              curve left-to-right, then `Z` — which draws a straight line from the
              END of the lower curve (x=1200) back to the START of the upper one
              (x=0). That single closing stroke cut a long diagonal straight
              across the whole wave, and with the fade mask removed it became
              clearly visible as a lit triangular sliver on one side and a dark
              wedge on the other.

              Reversing the second pass makes the two ends meet point-to-point, so
              the only closing segments are at x=0 and x=1200 — both far off-screen
              in the 170vw layers. No diagonal is drawn anywhere in frame. */}
          <path
            d={`M${crestCurve(phase, 430)} L${crestCurveBack(phase, 476)} Z`}
            fill={`url(#${uid}-foam)`}
            opacity="0.75"
          />
        </g>
      </svg>
    </div>
  )
}

/**
 * A crest curve across the viewBox.
 *
 * SAMPLED FROM A SUM OF SINES, not built from cubic control points. The earlier
 * version emitted `C cx,cy cx,cy x+200,y` — the same control point twice — which
 * produces a flat-topped bump per segment. Rendered small, that reads as a row of
 * angular zigzags, the opposite of a water swell. Sampling actual sine values and
 * joining them with a polyline gives a curve that is smooth at every scale, which
 * matters here because the SAME geometry is seen both as a distant ripple and,
 * a second later, filling the frame.
 *
 * The three terms are incommensurate (periods of about 3.1, 1.7 and 0.9 crests),
 * so the result never repeats visibly — a single sine reads as a drawn sine.
 * `phase` shifts it so the left and right waves are not the same shape mirrored.
 *
 * SAMPLE DENSITY. The same path is later scaled up ~2.6x by the approach
 * animation, which magnifies the polyline's segments with it. Ten samples per
 * crest left facets wide enough to see, and the water read as low-poly
 * mountains. The sample step is therefore fine enough that even magnified the
 * segments stay under two screen pixels — at which point the polyline and a
 * true curve are indistinguishable, for a fraction of the path-parsing cost of
 * beziers rebuilt per frame.
 */
function crestCurve(phase = 0, baseY = 420) {
  const points = []
  // 720 samples across the 1200-unit viewBox. The layer is ~170vw wide and the
  // viewBox is stretched to it by `preserveAspectRatio="none"`, so on a 1920px
  // screen one unit is ~2.7px and 240 samples would leave ~13px facets visibly
  // faceting the crest. 720 brings that under ~4px — smooth at every width.
  const SAMPLES = 720
  const STEP = 1200 / SAMPLES
  for (let x = 0; x <= 1200; x += STEP) {
    const t = (x / 1200) * Math.PI * 2
    const y =
      baseY +
      26 * Math.sin(t * 3 + phase * 1.7) +
      14 * Math.sin(t * 5 + phase * 2.6) +
      6 * Math.sin(t * 11 + phase * 0.9)
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return points.join(' L')
}

/**
 * The SAME crest, traced RIGHT-TO-LEFT, for closing a band cleanly.
 *
 * A filled band between two crest curves must return along the lower curve the
 * other way round, so the two ends meet point-to-point at x=0 and x=1200. Built
 * left-to-right and closed with `Z`, the path instead drew a straight diagonal
 * from the far end of the lower curve back to the near end of the upper one — a
 * visible stroke clean across the wave. Reversing here removes that diagonal
 * entirely; nothing has to be masked to hide it.
 */
function crestCurveBack(phase = 0, baseY = 420) {
  const points = []
  const SAMPLES = 720
  const STEP = 1200 / SAMPLES
  for (let x = 1200; x >= 0; x -= STEP) {
    const t = (x / 1200) * Math.PI * 2
    const y =
      baseY +
      26 * Math.sin(t * 3 + phase * 1.7) +
      14 * Math.sin(t * 5 + phase * 2.6) +
      6 * Math.sin(t * 11 + phase * 0.9)
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return points.join(' L')
}

/**
 * The overlay itself.
 *
 * It unmounts rather than staying in the tree hidden, so after the intro none of
 * these nodes exist at all — which is what keeps a later theme change or route
 * change from repainting a full-screen decorative layer.
 */
export default function SeaIntro() {
  const reduced = prefersReducedMotion()
  const [visible, setVisible] = useState(true)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    // Reduced motion still gets the intro, but as a brief static frame rather
    // than three seconds of movement: a completely instant cut is more jarring
    // than a short dissolve, and a full three seconds of motion is exactly what
    // the user asked not to see (requirement 9).
    const hold = reduced ? 250 : DURATION_MS
    const leave = reduced ? 200 : 400

    const leaveTimer = window.setTimeout(() => setLeaving(true), hold)
    const doneTimer = window.setTimeout(() => setVisible(false), hold + leave)

    return () => {
      window.clearTimeout(leaveTimer)
      window.clearTimeout(doneTimer)
    }
  }, [reduced])

  if (!visible) return null

  return (
    <div
      // `pointer-events-none` throughout: the Home page underneath is already
      // interactive and must stay so, and nothing here should ever intercept a
      // tap. `overflow-hidden` is the overflow guard (requirement 8) — the
      // waves are scaled well past the viewport edges, so without it they would
      // produce a horizontal scrollbar.
      className={`pointer-events-none fixed inset-0 z-[100] overflow-hidden ${leaving ? 'motion-safe:animate-intro-out' : ''
        }`}
      aria-hidden="true"
      data-testid="sea-intro"
    >
      {/* --- The empty blue field ------------------------------------------
          Requirement 1: a clean background with generous negative space, with
          no content on it at the start. A vertical gradient plus one soft light
          source, so it is a field rather than a flat rectangle.

          The three-stop Tailwind gradient banded badly on this panel: the stops
          are far apart in lightness, so 8-bit rounding produced a visible hard
          edge where sky-100 met sky-200. A gradient with many closely spaced
          stops spreads the transition across the whole height, which keeps each
          step below one lightness quantum — no band. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(to bottom, #e0f2fe 0%, #d9edfb 8%, #d1e8f8 17%, #cae4f5 25%, #c4e0f2 33%, #bcdcef 42%, #b5d6ec 50%, #aed2e9 58%, #a6cde6 67%, #a0c8e3 75%, #99c4e0 83%, #91bedd 92%, #8abada 100%)',
        }}
      />
      <div
        className="absolute inset-0 hidden dark:block"
        style={{
          background:
            'linear-gradient(to bottom, #0b1420 0%, #0a1727 8%, #091b2f 17%, #091f36 25%, #08223c 33%, #072644 42%, #07294b 50%, #062c52 58%, #05305a 67%, #043461 75%, #043767 83%, #033b6f 92%, #023e76 100%)',
        }}
      />

      {/* The light over the water. Decorative and static.

          A blurred DIV's edges became visible on this light background —
          blur-3xl is only 64px, not enough to dissolve a 70vw edge, so it read
          as diagonal streaks. A radial-gradient has no edge to blur: it fades
          to transparent BY CONSTRUCTION, so it cannot streak regardless of
          size. */}
      <div
        className="absolute left-1/2 top-[-15%] h-[60vh] w-[70vw] -translate-x-1/2"
        style={{
          background:
            'radial-gradient(50% 50% at 50% 50%, rgba(255,255,255,0.5) 0%, rgba(255,255,255,0.22) 45%, rgba(255,255,255,0) 100%)',
        }}
      />

      {/* --- The two approaching wave fronts ------------------------------
          Anchored to the bottom corners and sized to sit mostly OFF-screen, so
          at the start of the animation the only water visible is a pair of small
          distant swells in the corners — requirement 2. */}
      <div
        className="absolute inset-0"
        style={{
          // Perspective on the PARENT, so each child's growth is foreshortened as
          // it comes forward. Without it the scale is an even zoom and the
          // approach reads flat.
          perspective: '1200px',
          perspectiveOrigin: '50% 60%',
        }}
      >
        {/* Left front.

            WIDER THAN THE VIEWPORT BY A LOT (170vw), so its own box edges are
            always off-screen — at scale(0.12) the layer is still ~20vw, and at
            scale(2.6) it is ~440vw, either way covering the full frame edge to
            edge. That, together with the opaque mask in `Wave`, is what removes
            any visible left/right ending: the water is cut off only by the screen,
            never by its own shape.

            The layer is anchored to the bottom-LEFT corner and grows from there,
            so the water genuinely enters from the corner and sweeps across —
            which is why the scene never reads as a centred banner. */}
        <div
          className="absolute bottom-0 left-0 h-[62vh] w-[170vw] origin-bottom-left motion-safe:animate-intro-wave-left"
          // `both` fill is set in the Tailwind class; without it the wave would
          // spring back to scale(0.12) when the animation ends.
          style={{ transformOrigin: 'bottom left' }}
        >
          <Wave side="left" phase={0} className="h-full w-full" />
        </div>

        {/* Right front. Slightly delayed and at a different phase, so the two
            do not arrive as a mirrored pair. Anchored to the bottom-RIGHT corner
            so this front enters from the other corner. */}
        <div
          className="absolute bottom-0 right-0 h-[62vh] w-[170vw] origin-bottom-right motion-safe:animate-intro-wave-right"
          style={{
            transformOrigin: 'bottom right',
            // A small delay is what breaks the symmetry. The whole thing still
            // lands inside three seconds because the delay is short and the
            // animation is `both`-filled.
            animationDelay: '0.12s',
          }}
        >
          <Wave side="right" phase={1} className="h-full w-full" />
        </div>
      </div>

      {/* --- Internal water movement --------------------------------------
          Two soft swell bands drifting inside the body of the water, running
          against the approach so the surface is never static even after the
          waves have filled the frame (requirement 3, "flowing and floating
          gently in different directions").

          EVERY GRADIENT HERE REACHES ZERO BEFORE ITS DIV'S EDGE. The earlier
          bands centred their radial on the div's own boundary (`at 50% 0%`) and
          ended the shimmer's linear at a non-zero top stop, so the brightest
          part of each gradient was exactly where the div clipped it — which
          painted a hard horizontal line across the frame at the div's top edge
          (y=360 for the shimmer, y=480 for the swell). Centring each gradient
          inside its box and ending it at `transparent` removes the edge: there
          is nothing left to clip. */}
      <div className="absolute inset-x-0 bottom-0 h-[40vh] overflow-hidden" aria-hidden="true">
        <div className="absolute inset-y-0 -left-1/2 w-[200%] motion-safe:animate-intro-swell">
          <div className="h-1/2 w-full bg-[radial-gradient(38%_70%_at_50%_50%,rgba(255,255,255,0.26),rgba(255,255,255,0)_100%)]" />
          <div className="h-1/2 w-full bg-[radial-gradient(34%_65%_at_50%_50%,rgba(255,255,255,0.16),rgba(255,255,255,0)_100%)]" />
        </div>
      </div>

      {/* Caustic shimmer washing across the water. Its top stop is
          transparent, so the div's top edge cannot draw a line across the
          horizon. */}
      <div
        className="absolute inset-x-0 bottom-0 h-[55vh] motion-safe:animate-intro-shimmer"
        style={{
          background:
            'linear-gradient(to top, rgba(56,189,248,0.24) 0%, rgba(125,211,252,0.12) 40%, rgba(255,255,255,0) 80%)',
        }}
        aria-hidden="true"
      />

      {/* --- The wordmark --------------------------------------------------
          Fades in late, over the water that has already arrived, so the brand is
          the last thing the viewer sees before the page is revealed. It is
          marked `aria-hidden` because the overlay as a whole is decorative — a
          screen reader should get the Home page, not a logo. */}
      <div
        className="absolute inset-x-0 bottom-[16vh] flex flex-col items-center gap-2 motion-safe:animate-intro-mark"
        aria-hidden="true"
      >
        <span className="text-3xl font-semibold tracking-tight text-white drop-shadow-[0_2px_12px_rgba(3,105,161,0.55)] sm:text-4xl dark:text-aqua-50">
          AquaGuard AI
        </span>
        <span className="text-xs font-medium uppercase tracking-[0.28em] text-sky-100/85 dark:text-aqua-200/70">
          Water Quality Intelligence
        </span>
      </div>
    </div>
  )
}