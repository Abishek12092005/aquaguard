/**
 * STEP 28: THE LOCATION ACTION'S PIN — AN ANIMATED MARK, NOT AN EMOJI.
 *
 * The manual map button used to show "📍". A round-pin emoji is a typographic
 * character that the operating system draws, so it rendered as a flat yellow
 * pushpin on one machine and a different flat pushpin on another: it did not
 * match the aqua palette, it did not scale with the button, it did not respond to
 * hover, focus or dark mode, and no amount of styling could change any of that
 * because none of it belongs to the document. It was also the single loudest
 * thing in a toolbar of restrained line icons.
 *
 * This is the same pin drawn as SVG instead, so it is genuinely part of the
 * interface: it inherits `currentColor`, it is the brand aqua in both themes, and
 * every state below is animation the browser can honour.
 *
 * THE MARK NEVER MOVES. The pin body is drawn STILL in every mode and on every
 * screen — a location glyph that drifts or bounces is the "continuously moving
 * pin" the brief rules out, and on the Location Prediction screen it sits over a
 * map the user is about to aim at, where any movement of the marker itself is
 * actively unhelpful.
 *
 * WHAT `animated` DOES NOW is limited to a NON-SPATIAL accent: a soft pulse ring
 * at the pin's foot that fades in and out in place, and a gentle halo. Neither
 * translates, scales or rotates the pin, so the icon's position is pixel-stable
 * and only its emphasis changes. That is the professional "you are here" idiom —
 * the same one map applications use — without the floating/bob motion this
the brief forbids.
 *
 * THE DEFAULT IS STILL `animated = true` because the accent is safe to have on,
 * but every caller that wants absolute stillness (the Location Prediction
 * buttons, the permission popups, the inline text pills) passes
 * `animated={false}` explicitly, and those callers get a plain still SVG.
 *
 * REDUCED MOTION IS HONOURED GLOBALLY. `index.css` clamps every animation on the
 * page under `prefers-reduced-motion: reduce`, so a user who asked for less
 * motion gets the still pin without this component knowing or branching.
 */
export default function LocationPinIcon({ className = 'h-5 w-5', animated = true }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`${className} ${animated ? 'aqua-pin' : ''}`}
      aria-hidden="true"
      /* Decorative: the button it sits in carries the accessible name, and an
         animation is not content. */
      focusable="false"
    >
      {/* The halo. A FADE in place — it does not translate the pin. */}
      {animated && (
        <g className="aqua-pin-glow">
          <path
            d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"
            fill="currentColor"
            stroke="none"
            fillOpacity={0.22}
          />
        </g>
      )}

      {/* THE PIN BODY IS ALWAYS STILL.

          It used to carry `aqua-pin-body` (a 2px bob) when `animated` was set,
          which made the Recent Activity pin bob up and down forever. A location
          marker that floats is exactly the motion the brief rules out, so the
          body has no animation class at ANY setting — the icon's position cannot
          move, and `animated` only toggles the in-place pulse/halo below. */}
      <g>
        <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
        <circle cx={12} cy={10} r="3" fill="currentColor" stroke="none" />
      </g>

      {/* The pulse: a ring at the pin's foot that fades in place. Non-spatial,
          so it accents the mark without moving it. */}
      {animated && (
        <circle className="aqua-pin-pulse" cx={12} cy={21.5} r={2.2} fill="currentColor" stroke="none" />
      )}
    </svg>
  )
}
