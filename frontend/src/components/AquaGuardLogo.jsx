/**
 * AquaGuardLogo — the brand mark: a single photorealistic 3D water droplet.
 *
 * The mark used to be a neural network: a droplet feeding edges into hidden
 * nodes and out to a verdict node. It said a lot, but at the 36px it is
 * actually rendered at in the sidebar those edges and nodes were a few pixels
 * wide — they read as noise around a droplet rather than as a network. The
 * mark now says one thing clearly instead of two things illegibly.
 *
 * The droplet is the same material as the hero drop on the sign-in screen
 * (`WaterDrop3D`): the same five lighting cues are reproduced here so the logo
 * and the splash are visibly the same water, not two unrelated blue shapes.
 *
 *   1. base radial gradient   light bouncing through the body of the water
 *   2. a dark inner rim       the meniscus, where surface tension curves the edge
 *   3. specular highlights    a sharp primary catchlight + a soft secondary one
 *   4. a caustic bounce       the bright pool of light water throws back up
 *   5. a cast shadow          the drop's presence on the surface below it
 *
 * Animation, all of it optional (`animated={false}` renders it frozen):
 *   - the drop drips: it stretches under its own weight, releases, and settles
 *   - the catchlight shimmers across the body, which is what sells "wet" over
 *     "glossy plastic"
 *   - the cast shadow tightens as the drop stretches, so the two move together
 *   - ripple rings spread from the base, as if it had just landed
 *
 * Props:
 *   size      pixel size of the (square) mark
 *   animated  default true
 *   showText  render the AquaGuard AI wordmark beside the mark
 *   className passthrough
 */
export default function AquaGuardLogo({
  size = 44,
  animated = true,
  showText = false,
  className = '',
}) {
  // Gradient ids must be unique per instance. Two droplets on one page would
  // otherwise share ids, and the second would render with the first's colours.
  const uid = `ag${size}`
  const body = `${uid}-body`
  const rim = `${uid}-rim`
  const gloss = `${uid}-gloss`
  const caustic = `${uid}-caustic`
  const lighting = `${uid}-light`
  const halo = `${uid}-halo`

  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      {/* `viewBox` starts at y=-20 and `overflow` is visible for the same reason
          as WaterDrop3D: the drip keyframe stretches the group by 12% from a
          y=122 origin, which lifts the apex past the top of a `0 0 120 140` box
          and clips the tip off mid-animation. */}
      <svg
        width={size}
        height={size}
        viewBox="0 -20 120 160"
        overflow="visible"
        role="img"
        aria-label="AquaGuard AI"
        className="shrink-0"
      >
        <defs>
          {/* The body of the water. Bright at the upper-left where the light
              enters, deepening to a saturated blue at the lower-right where the
              water is thickest. This asymmetry is what makes it read as a
              volume rather than a flat sticker. */}
          {/* The body of the water.

              The `dark:` stops start at aqua-200 rather than pure white. At the
              36px this mark is actually rendered, a white highlight at offset 0%
              does not read as a catchlight — it floods the whole droplet, so the
              sidebar logo came out as a white blob instead of a blue drop. The
              white belongs in the specular highlights (drawn separately below),
              where it is small and bounded; the body gradient keeps some colour
              at every stop so the mark stays blue at any size. */}
          <radialGradient id={body} cx="35%" cy="28%" r="78%">
            <stop offset="0%" className="[stop-color:#ffffff] dark:[stop-color:#eaf7ff]" stopOpacity="0.98" />
            <stop offset="18%" className="[stop-color:#c9ecff] dark:[stop-color:#b8e4ff]" stopOpacity="0.95" />
            <stop offset="45%" className="[stop-color:#5cc0f5] dark:[stop-color:#3bb8ff]" stopOpacity="0.92" />
            <stop offset="72%" className="[stop-color:#0e9de8] dark:[stop-color:#0e9de8]" stopOpacity="0.95" />
            <stop offset="100%" className="[stop-color:#0163a0] dark:[stop-color:#007cc6]" stopOpacity="0.98" />
          </radialGradient>

          {/* Meniscus: the rim darkens because the surface curves away from the
              viewer and refracts the darker surroundings. */}
          <radialGradient id={rim} cx="50%" cy="45%" r="60%">
            <stop offset="70%" stopColor="#072c49" stopOpacity="0" />
            <stop offset="92%" stopColor="#072c49" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#072c49" stopOpacity="0.5" />
          </radialGradient>

          {/* The primary catchlight — a hard-edged bloom near the top-left. */}
          <radialGradient id={gloss} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="1" />
            <stop offset="55%" stopColor="#ffffff" stopOpacity="0.75" />
            <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
          </radialGradient>

          {/* Light that passed through the water and bounced off the surface
              beneath it — the bright pool at the base of the drop. */}
          <radialGradient id={caustic} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#e8faff" stopOpacity="0.85" />
            <stop offset="60%" stopColor="#a8e4ff" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#a8e4ff" stopOpacity="0" />
          </radialGradient>

          {/* A vertical sheen, as if a window were reflected in the upper half. */}
          <linearGradient id={lighting} x1="0%" y1="0%" x2="20%" y2="100%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.5" />
            <stop offset="40%" stopColor="#ffffff" stopOpacity="0.06" />
            <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
          </linearGradient>

          {/* A soft aqua halo, so the mark lifts off both the pale sidebar and
              the dark water backdrop instead of melting into either. */}
          <radialGradient id={halo} cx="50%" cy="50%" r="50%">
            <stop offset="0%" className="[stop-color:#7ed1ff] dark:[stop-color:#ffffff]" stopOpacity="0.4" />
            <stop offset="100%" className="[stop-color:#7ed1ff] dark:[stop-color:#ffffff]" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Ambient glow BEHIND the drop. Decorative only.

            The mark's ground: pale aqua in light mode, and a white lift in dark
            mode so the drop keeps a light surface under it rather than sitting
            directly on the dark sidebar. This is the "logo white" half — the
            drop stays blue in both themes, and it is the plate behind it that
            changes. */}
        <circle cx="60" cy="66" r="58" fill={`url(#${halo})`} />

        {/* --- Ripple rings: the drop just landed ---------------------------- */}
        {animated && (
          <g fill="none" stroke="#7ed1ff" strokeWidth="1.6">
            <ellipse
              cx="60"
              cy="130"
              rx="24"
              ry="6"
              className="motion-safe:animate-logo-ripple"
              style={{ transformOrigin: '60px 130px' }}
            />
            <ellipse
              cx="60"
              cy="130"
              rx="24"
              ry="6"
              className="motion-safe:animate-logo-ripple"
              style={{ transformOrigin: '60px 130px', animationDelay: '0.9s' }}
            />
          </g>
        )}

        {/* The droplet group carries the drip animation: stretch, release,
            settle. `origin` at the base keeps the stretch anchored where it
            would cling. */}
        <g
          className={animated ? 'motion-safe:animate-drop-drip' : undefined}
          style={{ transformOrigin: '60px 122px' }}
        >
          {/* --- Cast shadow on the surface below --------------------------- */}
          <ellipse
            cx="60"
            cy="130"
            rx="26"
            ry="6"
            fill="#0163a0"
            opacity="0.3"
            className={animated ? 'motion-safe:animate-drop-shadow' : undefined}
            style={{ transformOrigin: '60px 130px' }}
          />

          {/* --- The body of the drop --------------------------------------
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

          {/* --- Specular highlights --------------------------------------- */}
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

      {showText && (
        <span className="flex flex-col leading-none">
          <span className="text-sm font-semibold tracking-tight text-white">
            AquaGuard AI
          </span>
          <span className="mt-1 text-2xs font-medium uppercase tracking-wider text-aqua-200/80">
            Water Quality
          </span>
        </span>
      )}
    </span>
  )
}
