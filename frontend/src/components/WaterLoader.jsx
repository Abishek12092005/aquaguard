import { useMemo, useState } from 'react'

/**
 * WaterLoader — a full-screen loading state where the sea rises.
 *
 * WHAT IT IS. Rain falls from the top of the viewport, the sea floods up from
 * the bottom in waves, holds for a beat, and recedes. Everything about the water
 * is one object: surface, foam, swells, spray and bubbles all live inside a
 * single clipped block, so they rise together and the surface stays a surface.
 *
 * WHERE THE OLD STRAIGHT LINE WENT, AND WHY. The previous version painted a flat
 * band, gave it `animate-water-fill` (`scaleY`), and then drew a waterline on top
 * of it: a bright 2px bar plus two counter-scrolling wave SVGs pinned to the
 * band's top edge. Ink on the fill edge is a rule, and a rule sliding up a screen
 * is a progress bar — the animation read as a filled div with a line drawn on it,
 * which is exactly what it was.
 *
 * The fix is to stop drawing the surface and start *being* it:
 *
 *   1. The sea block is laid out at its full height (WATER_HEIGHT) and is not
 *      transformed at all.
 *   2. `animate-sea-rise` reveals it with `clip-path: inset()`, whose top edge is
 *      the fill boundary. That boundary is a curve, because the first thing
 *      inside the block is the crest — a wave path — not a border.
 *   3. Every band inside the block (foam, swells, deck movement) is positioned
 *      relative to the crest, so all of them are clipped by the same moving
 *      boundary. Nothing is left behind at a fixed height.
 *
 * So there is no line anywhere in the scene. The edge the user sees is the same
 * edge that hides the water, which is why it can never disagree with the fill.
 *
 * WHY 3 SECONDS, AND WHY IT LOOPS. A fast fill (1s, the previous value) reads as
 * a progress bar ticking, and at 1s the recede is so quick the sea never looks
 * like a body of water. Over 3s the crests are followable and the hold at the top
 * is long enough to register as "the water arrived". The cycle is deliberately
 * NOT tied to the request finishing — there is no progress value here, and a
 * loader that played once and then froze would look broken on exactly the slow
 * connection where the user is most anxious. A visibly repeating tide says "still
 * working" without promising a completion it cannot know.
 *
 * WHY IT RECEDES TO A FILM RATHER THAN TO NOTHING. The recede is the seam that
 * makes the repeat legible as a tide rather than a glitch, but taking it to zero
 * exposed the seabed for a frame and read as a reset. Holding 13% of water means
 * there is always sea on screen; only the depth changes.
 *
 * `motion-safe:` is used on every moving layer, so a user who asked for reduced
 * motion gets a still, half-filled sea instead of a frozen wave.
 */

// The depth of the sea block, as a percentage of the viewport. 45% means the sea
// tops out just above the middle of the screen, which leaves the rain room to be
// seen as rain and keeps the label clear of the water.
const WATER_HEIGHT = 45

export default function WaterLoader({ label = 'Loading…' }) {
  // The drops are generated once and never re-randomised. Regenerating them on
  // a re-render would restart every streak mid-flight, so the rain would
  // visibly stutter whenever the parent happened to render.
  const [drops] = useState(() => buildRain(38))

  // Same reasoning for the scene's populations: they are one-shot layouts, and
  // the motion afterwards is entirely CSS.
  const spray = useMemo(() => buildSpray(16), [])
  const bubbles = useMemo(() => buildBubbles(12), [])

  return (
    <div
      className="fixed inset-0 z-50 overflow-hidden bg-gradient-to-b from-aqua-50 via-aqua-100 to-aqua-200 dark:from-slate-950 dark:via-slate-950 dark:to-aqua-950"
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      {/* --- Sky glow: the low light over the water, so the top of the screen is
          not a flat panel. Purely decorative, and static. --- */}
      <span
        className="pointer-events-none absolute -top-24 left-1/2 h-64 w-[36rem] -translate-x-1/2 rounded-full bg-aqua-300/25 blur-3xl dark:bg-aqua-500/20"
        aria-hidden="true"
      />

      {/* --- 1. Rain: falls from above into the sea --- */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        {drops.map((drop) => (
          <span
            key={drop.id}
            className="absolute top-0 block rounded-full bg-aqua-400 motion-safe:animate-rain-fill dark:bg-aqua-300"
            style={{
              left: `${drop.left}%`,
              width: `${drop.width}px`,
              height: `${drop.length}px`,
              opacity: drop.opacity,
              animationDuration: `${drop.duration}s`,
              animationDelay: `${drop.delay}s`,
            }}
          />
        ))}
      </div>

      {/* --- 2. The sea ---------------------------------------------------
          One clipped block. Everything that is water lives in here, so the rise
          moves the surface and its contents as a single object. */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 motion-safe:animate-sea-rise"
        style={{ height: `${WATER_HEIGHT}%` }}
        aria-hidden="true"
      >
        {/* --- Body of the sea: darker at the seabed, the way depth actually
            reads. The top stop is deliberately only just lighter than the
            bottom — the surface itself is the waves above, not a gradient
            boundary, and a bright band here would reintroduce the "edge" the
            whole rewrite is removing. --- */}
        <span className="absolute inset-0 bg-gradient-to-b from-aqua-500/70 via-aqua-600/80 to-aqua-800/85 dark:from-aqua-600/60 dark:via-aqua-800/70 dark:to-aqua-950/85" />

        {/* --- Caustics: light refracting through the moving surface. Two
            out-of-phase washes rather than one, so the shimmer does not read as
            a pulsing blob. --- */}
        <span className="absolute -left-1/4 top-0 h-56 w-[70%] rounded-full bg-aqua-300/40 blur-3xl motion-safe:animate-sea-caustics dark:bg-aqua-400/25" />
        <span
          className="absolute right-0 top-4 h-48 w-[60%] rounded-full bg-aqua-200/35 blur-3xl motion-safe:animate-sea-caustics dark:bg-aqua-300/20"
          style={{ animationDelay: '-3.5s' }}
        />

        {/* --- Swells: the surface deck, moving sideways. `top-2` keeps it just
            under the crest so it lights the top of the water rather than the
            air above it. --- */}
        <span
          className="absolute inset-x-0 top-2 h-16 opacity-50 motion-safe:animate-sea-drift"
          style={{
            backgroundImage:
              'repeating-linear-gradient(115deg, rgba(255,255,255,0) 0px, rgba(255,255,255,0.30) 22px, rgba(255,255,255,0) 48px, rgba(255,255,255,0) 96px)',
          }}
        />

        {/* --- The crests (the curved surface itself) ------------------------
            The curve is NOT drawn here. It comes from `sea-rise`'s polygon: the
            top edge of the clipped shape is deliberately uneven, so the boundary
            between water and air is a real wave — refreshed at 60fps as the
            polygon interpolates, not faked with a bitmap edge.

            There used to be three scrolling SVG crest bands pinned to `top-0`
            here. They have been removed because they fought the polygon: the
            clip cuts a straight-edged shape down onto whatever sits inside it,
            so a band anchored at the block's top edge had its own crest sliced
            off flat and re-introduced the horizontal line. The polygon's edge
            replaced them — and with it gone there is exactly ONE thing defining
            the waterline, so the surface cannot disagree with the fill.

            What survives is the light ON the surface (below), which is additive
            and so cannot alter the edge. --- */}
        <span
          className="absolute inset-x-0 top-0 h-14 bg-gradient-to-b from-white/55 via-aqua-100/25 to-transparent motion-safe:animate-sea-drift dark:from-aqua-50/35 dark:via-aqua-200/15"
          style={{ animationDuration: '11s' }}
        />

        {/* --- The second surface -------------------------------------------
            A wave that drifts across the fill edge on its own clock, so the
            boundary the user sees is two curves crossing rather than one shape
            being animated.

            It is deliberately wider than the block and offset negatively on both
            sides, so its own left and right ends are always outside the visible
            area — a wave whose ends are on screen stops looking like a slice of
            water and starts looking like a drawn shape. */}
        <span
          className="absolute -left-[10%] -top-3 h-10 w-[120%] text-aqua-200/70 motion-safe:animate-sea-surface-drift dark:text-aqua-300/45"
          aria-hidden="true"
        >
          <svg
            viewBox="0 0 1440 40"
            preserveAspectRatio="none"
            fill="currentColor"
            className="h-full w-full"
          >
            {/* Seven crests across the width — a shorter wavelength than the
                clip polygon's, so the two curves interfere rather than sit on
                top of each other. */}
            <path d="M0,22 C90,4 180,36 270,18 C360,2 450,34 540,16 C630,0 720,32 810,16 C900,0 990,34 1080,18 C1170,4 1260,36 1350,20 C1390,12 1416,16 1440,18 L1440,40 L0,40 Z" />
          </svg>
        </span>

        {/* --- Foam: the bright lip riding the crest. It has to *fade* rather than
            travel — foam that arrives with the surface and then thins as the
            water settles is what sells the moment of arrival. It sits on the
            surface, so a soft vertical gradient is enough; nothing here draws an
            edge. --- */}
        <span className="absolute inset-x-0 top-0 h-12 bg-gradient-to-b from-white/70 via-aqua-100/40 to-transparent motion-safe:animate-sea-foam dark:from-aqua-100/40 dark:via-aqua-200/20" />

        {/* --- Sea spray: droplets flung out of the water, hanging, falling back.
            Positioned at the crest so they belong to it. --- */}
        {spray.map((drop) => (
          <span
            key={drop.id}
            className="absolute block rounded-full bg-white/80 motion-safe:animate-sea-spray dark:bg-aqua-100/70"
            style={{
              left: `${drop.left}%`,
              top: `${drop.top}rem`,
              height: `${drop.size}px`,
              width: `${drop.size}px`,
              animationDuration: `${drop.duration}s`,
              animationDelay: `${drop.delay}s`,
            }}
          />
        ))}

        {/* --- Bubbles: rising through the body of the water to the surface,
            where the block's own clip kills them as they arrive. --- */}
        {bubbles.map((bubble) => (
          <span
            key={bubble.id}
            className="absolute bottom-0 block rounded-full border-white/50 bg-white/20 motion-safe:animate-sea-bubble"
            style={{
              left: `${bubble.left}%`,
              height: `${bubble.size}px`,
              width: `${bubble.size}px`,
              animationDuration: `${bubble.duration}s`,
              animationDelay: `${bubble.delay}s`,
            }}
          />
        ))}

        {/* --- Seabed: the floor the whole thing is standing on, so the water has
            a bottom rather than fading out of the screen. --- */}
        <span className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-aqua-950/70 to-transparent dark:from-slate-950/80" />
      </div>

      

      {/* --- 3. The centred droplet and its label --------------------------

          The droplet is the loader's focus, so it sits at the TRUE centre of the
          screen on every viewport. It used to be anchored to the waterline
          (`bottom: CREST_TOP + 2.5rem`), which meant on a short window — a phone
          in landscape, or a laptop with the browser chrome taking a slice — the
          sea rose into the badge and the drop drifted off-centre above it.

          Now the scene is a single flex column pinned to the viewport
          (`fixed inset-0`), centred both ways, and it cannot be pushed around by
          the water height. The `translateY(-50%)` from a `top-1/2` anchor is the
          other half of that centring: the column's own height, not the screen's,
          decides where its middle is.

          Order is droplet FIRST, label BELOW it. `flex-col` gives that for free,
          and `gap` is the space between them — the requirement is explicitly
          "Loading under the drop", so the label is a sibling that follows the
          droplet rather than a caption floating over the sea. */}
      <div
        // `flex` is required for `flex-col` and the centring to do anything — the
        // class list had `flex-col items-center justify-center` but no `flex`, so
        // the column was never a flex container: it was a plain block pinned to the
        // top-left with the droplet and the label stacked as ordinary block-level
        // children. That is why the drop was not centred.
        //
        // `inset-0` stretches the layer over the whole viewport, and
        // `items-center justify-center` centres it on BOTH axes, so the droplet
        // lands on the true centre of whatever screen the loader is shown on —
        // phone, tablet or desktop — with no transform trickery to go wrong on a
        // short window. The label is a following sibling in the same column, so it
        // sits directly UNDER the drop as the requirement asks.
        className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-4 px-6 text-center"
      >
        <span
          className="relative flex h-16 w-16 items-center justify-center motion-safe:animate-sea-bob"
          aria-hidden="true"
        >
          <span className="absolute h-14 w-14 rounded-full bg-aqua-400/30 motion-safe:animate-pulse-ring" />
          <svg viewBox="0 0 24 24" fill="currentColor" className="relative h-9 w-9 text-aqua-600 dark:text-aqua-300">
            <path d="M12 3c4 5 6 8 6 11a6 6 0 0 1-12 0c0-3 2-6 6-11Z" />
          </svg>
        </span>
        <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{label}</p>
      </div>
    </div>
  )
}

// The `WaveField` helper and its scrolling crest bands used to live here. They
// were removed once the surface moved into the `sea-rise` polygon: with the clip
// boundary supplying the curve, a band pinned to the block's top edge was simply
// cut flat by that same boundary, and there would have been two things defining
// the waterline that could disagree about where it was.

/**
 * Deterministic rain layout for the sky above the sea.
 *
 * The golden-ratio step spreads points evenly across the full width at any
 * count. A `(id * k) % 100` sequence with a large k looks random but is not: it
 * walks the range in fixed strides and leaves whole bands empty, which on a
 * full-screen loader is immediately obvious as "it only rains on the right".
 */
function buildRain(count) {
  const PHI = 0.6180339887498949
  return Array.from({ length: count }, (_, id) => ({
    id,
    left: Math.round(((id * PHI) % 1) ** 0.85 * 100 * 100) / 100,
    // Length and speed vary together: a long streak that also fell fast would
    // read as a scratch on the screen, whereas length + speed + opacity moving
    // as a group is what the eye reads as distance from the viewer.
    length: 26 + ((id * 37) % 54),
    width: id % 5 === 0 ? 2 : 1,
    // Every drop completes its journey within the cycle, staggered so the rain
    // is continuous rather than a synchronised sheet.
    duration: 0.55 + ((id * 29) % 40) / 100,
    delay: -(((id * 71) % 100) / 100),
    opacity: 0.25 + ((id * 53) % 45) / 100,
  }))
}

/**
 * Spray thrown up from the crest.
 *
 * `top` is in rem and lives in the small band either side of the crest (the
 * negative offsets are droplets below the surface line, so the sea hides where
 * they are born). Speeds are staggered hard — a synchronised burst reads as one
 * object, individual droplets read as spray.
 */
function buildSpray(count) {
  const PHI = 0.6180339887498949
  return Array.from({ length: count }, (_, id) => ({
    id,
    left: Math.round(((id * PHI) % 1) * 100 * 100) / 100,
    top: -0.25 + ((id * 17) % 10) / 10,
    size: 3 + ((id * 7) % 4),
    duration: 1.3 + ((id * 23) % 90) / 100,
    delay: -(((id * 41) % 200) / 100),
  }))
}

/** Bubbles inside the water, spread evenly for the same low-discrepancy reason. */
function buildBubbles(count) {
  const PHI = 0.6180339887498949
  return Array.from({ length: count }, (_, id) => ({
    id,
    left: Math.round(((id * PHI) % 1) * 100 * 100) / 100,
    size: 4 + ((id * 13) % 12),
    duration: 9 + ((id * 47) % 80) / 10,
    delay: -(((id * 83) % 170) / 10),
  }))
}
