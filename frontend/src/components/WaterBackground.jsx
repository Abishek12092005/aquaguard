import { useMemo } from 'react'

/**
 * Full-bleed animated water backdrop.
 *
 * Renders four stacked, purely decorative layers behind the application:
 *
 *   1. caustic  — two slow, out-of-phase radial washes that drift like light
 *                 refracting through a moving surface
 *   2. waves    — two SVG wave bands scrolling against each other at the bottom
 *   3. rain     — falling drops, each its own streak length/speed/opacity
 *   4. bubbles  — rising droplets inside the scene, for the "underwater" read
 *
 * Sizing: the backdrop is `fixed inset-0`, i.e. always exactly one viewport.
 * That is deliberate and load-bearing. Making it `absolute`/page-height instead
 * inflates the scroll container: `html`, `body` and `#root` are all `height:
 * 100%`, so a full-document-height child overflows a fixed-height root and the
 * page stops scrolling entirely. A viewport-sized fixed layer contributes
 * nothing to layout, and because it does not move with the scroll it keeps the
 * rain falling across the whole document for free.
 *
 * Consequence to be aware of: the wave bands and the deep-water floor are
 * pinned to the bottom of the *viewport*, not the document, so they travel with
 * the user as they scroll rather than being seen once at the end of the page.
 *
 * Design rules that keep this from becoming noise:
 *   - every layer is `pointer-events-none` and `aria-hidden`, so it can never
 *     intercept a click or be announced by a screen reader
 *   - the whole thing is wrapped in `motion-safe:` variants — a user who has
 *     asked for reduced motion gets a still gradient, not a frozen animation
 *   - only transform/opacity animate, so it composites on the GPU and costs
 *     essentially nothing on a low-end laptop
 *
 * Props:
 *   variant  'app'  subtle, for behind dense data screens (default)
 *            'hero' stronger, for the login / register splash
 */
export default function WaterBackground({ variant = 'app', className = '' }) {
  const hero = variant === 'hero'

  // The droplets are generated once per mount. Recomputing them on every render
  // would restart each animation mid-flight, so the layout is memoised and only
  // the CSS keyframes drive movement afterwards.
  // Drop count is a legibility/sparseness trade-off, and it has moved twice.
  // 46 was invisible; 120 read as a downpour and was too busy — the eye could
  // not follow a single drop, so the scene felt like static rather than rain.
  // 48 was still too dense on the auth splash: the falling drops competed with
  // the wordmark and the card, reading as background noise. 24 large, slow
  // streaks leave visible empty water between them, so the eye can follow one
  // drop all the way down — which is what makes it read as water, not texture.
  const drops = useMemo(() => buildDrops(hero ? 24 : 14, hero), [hero])
  const bubbles = useMemo(() => buildBubbles(hero ? 12 : 8, hero), [hero])

  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none fixed inset-0 -z-10 overflow-hidden ${
        // The hero is deliberately dark — white rain needs contrast to exist.
        // The stops travel a long way (near-black surface → luminous mid-water)
        // rather than sitting in three similar mid-blues, which is what made
        // the earlier version read as one flat slab of colour.
        //
        // The app backdrop is NOT the hero gradient played quieter. It is a
        // *token* wash at low alpha, so the light page behind it does most of
        // the work and the animation is a moving tint rather than a wall of
        // colour. `bg-water-body-dark` used to sit here, but a full-opacity
        // mid-blue layer over a fixed viewport is dark by construction: it
        // covered everything below the topbar and there was no lightening it
        // without changing how it was built. See index.css.
        hero ? 'bg-hero-water' : 'bg-water-veil'
      } ${className}`}
    >
      {/* --- 1. Light caustics --------------------------------------------
          Brighter on the hero: these are the "light through moving water"
          pools, and on the dark hero background they are what gives the scene
          depth and a sense of surface above the rain. */}
      <span
        className={`absolute -left-1/4 -top-1/3 h-[38rem] w-[38rem] rounded-full blur-3xl motion-safe:animate-drift-slow ${
          hero ? 'bg-aqua-400/45' : 'bg-aqua-400/25'
        }`}
        style={{ animationDuration: '26s' }}
      />
      <span
        className={`absolute -right-1/4 top-1/4 h-[32rem] w-[32rem] rounded-full blur-3xl motion-safe:animate-drift-reverse ${
          hero ? 'bg-aqua-300/40' : 'bg-aqua-300/30'
        }`}
        style={{ animationDuration: '34s' }}
      />
      <span
        className={`absolute bottom-0 left-1/3 h-[28rem] w-[28rem] rounded-full blur-3xl motion-safe:animate-drift-slow ${
          hero ? 'bg-aqua-500/40' : 'bg-aqua-500/20'
        }`}
        style={{ animationDuration: '30s', animationDelay: '-8s' }}
      />

      {/* --- 2. Waves ------------------------------------------------------
          Tinted toward the deep end of the palette (500–700 rather than
          200–400). At 200-level tints and 20% opacity the bands simply
          disappeared into the background on a real screen. */}
      <WaveBand
        className="bottom-[-1px] h-32 text-aqua-500/40 motion-safe:animate-wave-slow sm:h-40"
        path="M0,64 C240,96 480,16 720,48 C960,80 1200,32 1440,64 L1440,160 L0,160 Z"
      />
      <WaveBand
        className="bottom-[-1px] h-24 text-aqua-600/35 motion-safe:animate-wave-mid sm:h-32"
        path="M0,80 C320,32 560,112 880,72 C1120,42 1280,96 1440,64 L1440,160 L0,160 Z"
      />
      {hero && (
        <WaveBand
          className="bottom-[-1px] h-16 text-aqua-700/30 motion-safe:animate-wave-fast sm:h-20"
          path="M0,96 C260,64 520,128 780,96 C1040,64 1240,120 1440,88 L1440,160 L0,160 Z"
        />
      )}

      {/* --- 3. Rain -------------------------------------------------------
          A hairline one pixel wide is invisible once it is translucent over a
          pale background, so each drop is a thread of solid colour that fades
          only at its tip. The gradient is set in JS rather than Tailwind so the
          hero and app palettes can differ without two class branches. */}
      <div className="absolute inset-0">
        {drops.map((drop) => (
          <span
            key={drop.id}
            className="absolute top-[-22%] block motion-safe:animate-rain-fall"
            style={{
              left: `${drop.left}%`,
              width: `${drop.width}px`,
              height: `${drop.length}px`,
              opacity: drop.opacity,
              borderRadius: '9999px',
              // Both variants now paint LIGHT streaks, because both sit on a
              // dark ground. The app variant used to be dark blue
              // (`rgba(1,99,160,...)`) to show up against the old near-white
              // `bg-water-body`; once the app backdrop went dark that would have
              // been dark-on-dark and vanished entirely. The app streaks are
              // kept a little dimmer and cooler than the hero's so they stay
              // background texture rather than competing with data on the cards.
              backgroundImage: hero
                ? 'linear-gradient(to bottom, rgba(255,255,255,0) 0%, rgba(255,255,255,1) 25%, rgba(255,255,255,0.35) 100%)'
                : 'linear-gradient(to bottom, rgba(255,255,255,0) 0%, rgba(248,253,255,0.6) 28%, rgba(201,236,255,0.16) 100%)',
              // A slight glow so a streak reads as catching the light rather
              // than as a flat white line.
              boxShadow: hero
                ? '0 0 6px rgba(255,255,255,0.45)'
                : '0 0 5px rgba(255,255,255,0.3)',
              animationDuration: `${drop.duration}s`,
              animationDelay: `${drop.delay}s`,
            }}
          />
        ))}
      </div>

      {/* --- 4. Rising droplets ------------------------------------------- */}
      <div className="absolute inset-0">
        {bubbles.map((bubble) => (
          <span
            key={bubble.id}
            className="absolute bottom-[-8%] block rounded-full motion-safe:animate-bubble-rise"
            style={{
              left: `${bubble.left}%`,
              height: `${bubble.size}px`,
              width: `${bubble.size}px`,
              // Light rims for both variants, matching the rain. The app rims sit
              // against a pale veil now, so they are white-with-alpha rather than
              // the old aqua — an aqua rim on a pale aqua wash is invisible.
              border: hero
                ? '1px solid rgba(255,255,255,0.55)'
                : '1px solid rgba(255,255,255,0.5)',
              backgroundColor: hero ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.2)',
              animationDuration: `${bubble.duration}s`,
              animationDelay: `${bubble.delay}s`,
            }}
          />
        ))}
      </div>

      {/* Deep-water floor — the visual bottom of the scene, so the backdrop
          has depth instead of reading as an even pale wash. */}
      <span
        className={`absolute inset-x-0 bottom-0 bg-gradient-to-t to-transparent ${
          // The hero can afford a near-opaque seabed; the app screen cannot.
          // At `from-aqua-900/50` this floor was the single darkest thing in
          // the app backdrop — 50% of a near-black navy laid across the bottom
          // half of every authenticated screen, with nothing to lighten it.
          // This is the second lever on how deep the water reads: the veil sets
          // the overall tint, the floor sets how much weight collects at the
          // bottom of the screen.
          hero ? 'h-72 from-aqua-800/55' : 'h-44 from-aqua-700/40'
        }`}
      />

      {/* --- 5. Depth field -----------------------------------------------
          The layers above are sized in viewport units, so on a page taller
          than one screen (a full dashboard, a long history table) the water
          visibly ran out below the fold and left a flat band. These two
          tiled, slowly-scrolling fields continue the rainfall and the swell
          all the way down the document, so there is motion at every scroll
          position. Both are cheap: a repeating background-image moved with a
          transform, not hundreds of extra elements. */}
      {!hero && (
        <>
          {/* Rain streaks, tiled. Light rather than the old dark blue, because
              the app ground is dark now — see the drop gradient above. */}
          <span
            className="absolute inset-0 opacity-[0.4] motion-safe:animate-rain-field"
            style={{
              backgroundImage:
                'linear-gradient(to bottom, rgba(255,255,255,0) 0%, rgba(255,255,255,0.5) 45%, rgba(255,255,255,0.08) 100%)',
              backgroundSize: '38px 190px',
              backgroundRepeat: 'repeat',
              // Only the first column is drawn as a streak; the repeat carries
              // the pattern, so the gradient is clipped to a thin vertical band.
              //
              // Soft-edged (0.6px → 1.6px → gone) rather than the hard 1.5px step
              // this started as. Hard mask edges on a fixed-alpha gradient are
              // exactly what produces visible banding, and the whole mask is on
              // the *vertical* axis, so a stiff edge here contributes to the
              // horizontal-stripe problem rather than being part of the fix.
              maskImage:
                'repeating-linear-gradient(to right, transparent 0px, #000 0.6px, #000 1.6px, transparent 2.6px, transparent 38px)',
              WebkitMaskImage:
                'repeating-linear-gradient(to right, transparent 0px, #000 0.6px, #000 1.6px, transparent 2.6px, transparent 38px)',
            }}
          />
          {/* Broad swell bands sweeping across the page body.

              This was a hard-edged `rgba(255,255,255,0.55) 0px → 2px → transparent`
              band repeating every 128px, and it moved. That is not a swell, it is
              a drawn line: a crisp 2px edge at every tile boundary, sliding down
              the page on a loop, which read unmistakably as horizontal stripes
              rather than as water.

              A swell has no edge, so this is now a genuine gradient — the band
              fades in over the top half of the tile and out over the bottom
              half, with no step anywhere in the cycle. The tile and the travel
              distance still match (128px), so the loop stays seamless.

              Colour is aqua rather than white for the same reason as the veil:
              white over a pale ground lightens without adding depth. */}
          <span
            className="absolute inset-0 opacity-[0.55] motion-safe:animate-swell"
            style={{
              backgroundImage:
                'repeating-linear-gradient(to bottom, rgba(126,209,255,0) 0px, rgba(126,209,255,0.22) 64px, rgba(126,209,255,0) 128px)',
            }}
          />
        </>
      )}
    </div>
  )
}

/** One parallax wave band pinned to the bottom edge of the backdrop. */
function WaveBand({ className = '', path }) {
  return (
    <svg
      className={`absolute left-0 w-[200%] ${className}`}
      viewBox="0 0 1440 160"
      preserveAspectRatio="none"
      fill="currentColor"
    >
      <path d={path} />
    </svg>
  )
}

// --- generators ------------------------------------------------------------

/**
 * Deterministic layout for the falling drops.
 *
 * `heavy` is the hero setting. It produces thicker, faster, more opaque streaks
 * at higher density, because a storm has to be unambiguous — the app backdrop
 * can afford to whisper, the login screen cannot.
 *
 * Width is the single most important value here. A 1px line is a sub-pixel
 * feature on many displays: anti-aliasing smears it into the background and it
 * reads as haze rather than rain. The hero therefore uses 2px and 3px strokes.
 */
function buildDrops(count, heavy = false) {
  return Array.from({ length: count }, (_, id) => {
    const bias = id % 3 === 0 ? 1 : 0 // a few heavier streaks among the light ones
    return {
      id,
      // Horizontal position, and the reason the left third of the screen used
      // to have almost nothing in it.
      //
      // The previous formula was `(id * 97) % 100`. 97 is coprime with 100, but
      // that does not make the sequence spread out: it steps by -3 every time
      // (97 ≡ -3 mod 100), so 24 drops only ever visited 24 of 34 possible
      // values and clustered wherever the cycle landed. Measured on the real
      // hero spread, the four screen quarters held 1 / 7 / 8 / 8 drops — the
      // left quarter had a single streak, which is exactly the "it only rains
      // on the middle and right" the user saw.
      //
      // A low-discrepancy (golden-ratio) step spreads every count evenly across
      // the full width instead. phi = 0.618..., so `id * phi` fills 0–1 without
      // repeating, and multiplying by 100 gives a percentage. Same math for 14
      // drops as for 24: no quarter of the screen can starve.
      //
      // `** 0.85` pushes points slightly toward the edges. Random rain looks
      // most even when it is uniform, but drawn uniform it can read as evenly
      // spaced columns; this de-regularises it without reopening a gap.
      left: round(((id * 0.6180339887498949) % 1) ** 0.85 * 100),
      length:
        (heavy ? 70 : 50) + ((id * 37) % (heavy ? 80 : 70)) + bias * (heavy ? 45 : 35),
      width: heavy ? (id % 4 === 0 ? 3 : 2) : id % 5 === 0 ? 2 : 1,
      // Fall time. The hero was 0.7–1.6s, which is genuinely fast rain but read
      // as visual noise: the eye tracks a streak for a few frames and it is
      // gone, so the scene feels like static. 2.6–4.4s was followable but still
      // hurried on the auth splash, where the animation is the whole backdrop.
      // 5.0–8.0s hero / 3.4–5.2s app is a genuine drift downward: a drop is
      // trackable start to finish and the scene reads as calm water, not rain.
      duration: round((heavy ? 5 : 3.4) + ((id * 53) % (heavy ? 300 : 180)) / 100),
      delay: round(-((id * 71) % 320) / 100),
      // Slightly softer too: at slower speeds a fully opaque streak looks
      // painted on, whereas a little translucency reads as refracted light.
      opacity: round((heavy ? 0.5 : 0.4) + ((id * 29) % (heavy ? 30 : 40)) / 100),
    }
  })
}

/** Deterministic layout for the bubbles rising through the scene. */
function buildBubbles(count, heavy = false) {
  return Array.from({ length: count }, (_, id) => ({
    id,
    left: round((id * 61) % 100),
      size: (heavy ? 8 : 6) + ((id * 13) % (heavy ? 26 : 18)),
    // Bubbles rise slowly on the hero now that fewer of them are on screen, and
    // slower again so their pace sits with the calmer 5–8s rain rather than
    // outrunning it.
    duration: round((heavy ? 14 : 11) + ((id * 47) % 90) / 10),
    delay: round(-((id * 83) % 140) / 10),
  }))
}

/** Trim to 3 decimals so the inline styles stay short. */
function round(value) {
  return Math.round(value * 1000) / 1000
}
