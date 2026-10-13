import { ICONS } from '@/config/navigation'

/**
 * Inline SVG icon.
 *
 * Stroked line icons with `currentColor`, so an icon inherits the text colour
 * of whatever it sits in and active/hover states need no extra CSS.
 *
 * `path` MAY BE AN ICON NAME. Callers pass `path={ICONS.location}` in most places
 * but `path="location"` in others, and the two forms are indistinguishable at the
 * call site - a name that is not resolved is not a missing icon, it is a MALFORMED
 * PATH, and the browser discards the whole <path> so the icon silently vanishes.
 * Resolving here makes both forms correct instead of relying on every call site.
 *
 * Anything that is neither a known name nor plausible path data falls back to the
 * info mark, so a typo degrades to a visible generic icon rather than to nothing.
 */
export default function Icon({ path, className = 'h-5 w-5', strokeWidth = 1.8, ...rest }) {
  const named = ICONS[path]
  // Real path data always starts with a moveto. No ICONS key does, so this test
  // can never misread a name as data or data as a name.
  const looksLikePath = typeof path === 'string' && /^[Mm]/.test(path)
  const d = named || (looksLikePath ? path : ICONS.info)
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...rest}
    >
      <path d={d} />
    </svg>
  )
}
