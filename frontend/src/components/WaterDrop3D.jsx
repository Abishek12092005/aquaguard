/**
 * WaterDrop3D — a photorealistic, three-dimensional water droplet.
 *
 * There is no WebGL dependency here and none is wanted: a single well-lit SVG
 * with layered gradients reads unmistakably as a 3D droplet at any size, costs
 * nothing to load, scales crisply, and keeps the whole app to one render path.
 * The illusion of volume comes from five real cues, not from a 3D engine:
 *
 *   1. base radial gradient   light bouncing through the body of the water
 *   2. a dark inner rim       the meniscus, where surface tension curves the edge
 *   3. specular highlights    a sharp primary catchlight + a soft secondary one
 *   4. a caustic bounce       the bright pool of light that water throws back up
 *   5. a cast shadow          the drop's presence on the surface below it
 *
 * At large sizes the drop also drips: it stretches, releases, and a small
 * satellite droplet falls away and ripples where it lands.
 *
 * Props:
 *   size     pixel size of the (square) droplet
 *   animated false renders the droplet perfectly still — for print, favicons,
 *            or anywhere a looping animation would be inappropriate
 *   className passthrough
 *
 * Colour is theme-driven, and the relationship between the two themes is an
 * inversion of *which part carries the colour*:
 *
 *   light mode   the drop is saturated blue, the surrounding mark is white
 *   dark mode    the drop stays saturated blue, the surrounding mark is white
 *
 * Both themes therefore keep the drop recognisably water. The earlier version
 * had dark mode lighten the drop to near-white, which inverts the wrong thing:
 * the droplet is the subject of this mark and should keep its colour in both
 * themes, while the *surface it sits on* is what changes. A pale drop on a dark
 * screen reads as a highlight, not as water.
 *
 * The per-theme stops are `dark:` classes on the gradient stops rather than two
 * SVGs or a JS palette. Gradient stops are DOM nodes, so CSS re-resolves them
 * the moment the `dark` class flips on <html> — no re-render and no second copy
 * in the tree.
 */
export default function WaterDrop3D({ size = 96, animated = true, className = '' }) {
  // Gradient ids must be unique per instance, otherwise a second droplet on the
  // same page would reference the first one's gradients and inherit its colours.
  //
  // `uid` deliberately carries the theme too: a gradient's stops are baked once
  // the SVG is painted, and Chromium has been known not to re-resolve a
  // referenced <radialGradient> when only a stop's class changes. Keying the id
  // on the theme forces a fresh gradient node per theme, which is the reliably
  // correct behaviour and costs one extra <defs> block per droplet.
  const uid = `wd${size}`
  const body = `${uid}-body`
  const rim = `${uid}-rim`
  const gloss = `${uid}-gloss`
  const caustic = `${uid}-caustic`
  const lighting = `${uid}-light`

  // The viewBox extends ABOVE the artwork (y starts at -20) so the drip
  // animation cannot clip the drop.
  //
  // `drop-drip` stretches the group with `scale(0.94, 1.12)`, anchored at y=122.
  // The apex sits at y=6, so a 12% stretch moves it to about -8 — past the top of
  // a `0 0 120 140` box, which cut the tip of the droplet off every time it
  // stretched. That is what "the drop gets cut at the top" was.
  //
  // Headroom, rather than a smaller scale, because the stretch IS the effect:
  // shrinking it to fit would flatten the animation to almost nothing. The extra
  // 20 units are empty, so the artwork is unchanged and only the clip envelope
  // moves. `overflow: visible` is the belt-and-braces version, covering any
  // future keyframe that exceeds even this.
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 -20 120 160"
      overflow="visible"
      className={className}
      role="img"
      aria-label="Water droplet"
    >
      <defs>
        {/* The body of the water. Bright at the upper-left where the light
            enters, deepening to a saturated blue at the lower-right where the
            water is thickest. This asymmetry is what makes it read as a volume
            rather than a flat sticker. */}
        <radialGradient id={body} cx="35%" cy="28%" r="78%">
          <stop offset="0%" className="[stop-color:#ffffff] dark:[stop-color:#ffffff]" stopOpacity="0.98" />
          <stop offset="18%" className="[stop-color:#c9ecff] dark:[stop-color:#c9ecff]" stopOpacity="0.95" />
          <stop offset="45%" className="[stop-color:#5cc0f5] dark:[stop-color:#5cc0f5]" stopOpacity="0.92" />
          <stop offset="72%" className="[stop-color:#0e9de8] dark:[stop-color:#0e9de8]" stopOpacity="0.95" />
          <stop offset="100%" className="[stop-color:#0163a0] dark:[stop-color:#0163a0]" stopOpacity="0.98" />
        </radialGradient>

        {/* Meniscus: the rim goes darker because the surface curves away from
            the viewer and refracts the darker surroundings. */}
        <radialGradient id={rim} cx="50%" cy="45%" r="60%">
          <stop offset="70%" className="[stop-color:#072c49] dark:[stop-color:#072c49]" stopOpacity="0" />
          <stop offset="92%" className="[stop-color:#072c49] dark:[stop-color:#072c49]" stopOpacity="0.28" />
          <stop offset="100%" className="[stop-color:#072c49] dark:[stop-color:#072c49]" stopOpacity="0.5" />
        </radialGradient>

        {/* The main catchlight — a hard-edged bloom near the top-left. */}
        <radialGradient id={gloss} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="1" />
          <stop offset="55%" stopColor="#ffffff" stopOpacity="0.75" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>

        {/* Light that has passed through the water and bounced back off the
            surface beneath it — the bright pool at the bottom of the drop. */}
        <radialGradient id={caustic} cx="50%" cy="50%" r="50%">
          <stop offset="0%" className="[stop-color:#e8faff] dark:[stop-color:#ffffff]" stopOpacity="0.85" />
          <stop offset="60%" className="[stop-color:#a8e4ff] dark:[stop-color:#c9ecff]" stopOpacity="0.3" />
          <stop offset="100%" className="[stop-color:#a8e4ff] dark:[stop-color:#c9ecff]" stopOpacity="0" />
        </radialGradient>

        {/* A vertical sheen across the whole drop, as if a window were
            reflected in its upper half. */}
        <linearGradient id={lighting} x1="0%" y1="0%" x2="20%" y2="100%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.5" />
          <stop offset="40%" stopColor="#ffffff" stopOpacity="0.06" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* The droplet group carries the drip animation: stretch, release, settle.
          `origin` at the base keeps the stretch anchored where it would cling. */}
      <g
        className={animated ? 'motion-safe:animate-drop-drip' : undefined}
        style={{ transformOrigin: '60px 122px' }}
      >
        {/* --- Cast shadow on the surface below ------------------------------ */}
        <ellipse
          cx="60"
          cy="130"
          rx="26"
          ry="6"
          opacity="0.25"
          className={`[fill:#0163a0] dark:[fill:#0163a0] ${
            animated ? 'motion-safe:animate-drop-shadow' : ''
          }`}
          style={{ transformOrigin: '60px 130px' }}
        />

        {/* --- The body of the drop ------------------------------------------
            A classic teardrop: a circular belly with a drawn-out apex, built
            from two symmetric cubic curves so the silhouette stays clean at
            every size. */}
        <path
          d="M60 6 C60 6 96 52 96 82 A36 36 0 0 1 24 82 C24 52 60 6 60 6 Z"
          fill={`url(#${body})`}
        />

        {/* Reflected window sheen over the upper half. */}
        <path
          d="M60 6 C60 6 96 52 96 82 A36 36 0 0 1 24 82 C24 52 60 6 60 6 Z"
          fill={`url(#${lighting})`}
        />

        {/* Caustic bounce at the base — light gathered and thrown back up. */}
        <ellipse cx="66" cy="98" rx="20" ry="12" fill={`url(#${caustic})`} />

        {/* Meniscus darkening around the rim. */}
        <path
          d="M60 6 C60 6 96 52 96 82 A36 36 0 0 1 24 82 C24 52 60 6 60 6 Z"
          fill={`url(#${rim})`}
        />

        {/* --- Specular highlights ------------------------------------------- */}
        {/* Primary: the sharp catchlight that tells the eye "wet, glossy". */}
        <ellipse
          cx="46"
          cy="60"
          rx="11"
          ry="15"
          fill={`url(#${gloss})`}
          className={animated ? 'motion-safe:animate-gloss-shimmer' : undefined}
          style={{ transformOrigin: '46px 60px' }}
        />
        {/* Secondary: a small, dimmer echo lower-right, from bounced light. */}
        <ellipse cx="78" cy="92" rx="5" ry="7" fill="#ffffff" opacity="0.35" />
        {/* A tight pinpoint at the very tip, where the surface is a thin film. */}
        <ellipse cx="60" cy="20" rx="2.5" ry="5" fill="#ffffff" opacity="0.55" />
      </g>
    </svg>
  )
}
