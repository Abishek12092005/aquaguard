import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

/**
 * THE LOCATION SUGGESTION DROPDOWN, SHARED BY EVERY LOCATION SEARCH BOX.
 *
 * It is rendered through a PORTAL to <body>, and that is the whole reason this
 * component exists. Both screens that use it (Location Prediction and Rainy
 * Alerts) render their search box inside a <Card>, and `.card` carries
 * `overflow-hidden` so the history table can never paint past its rounded
 * edge — which also clipped any absolutely-positioned suggestion list at the
 * card's bottom border. A list that shows one suggestion and swallows the rest
 * is worse than no list, so the dropdown now lives outside the card entirely:
 * fixed-positioned under the input's current viewport rectangle, it cannot be
 * clipped by any ancestor, hidden behind the map, or covered by the topbar.
 *
 * MEASUREMENT AND REPOSITIONING. The panel is positioned from the input's
 * `getBoundingClientRect()` the moment it opens, and re-measured on every
 * scroll (capture phase, so scrolls inside inner containers count too) and on
 * window resize. The panel therefore follows the field when the page scrolls
 * rather than being left floating where the input used to be.
 *
 * HEIGHT. The panel is DYNAMIC: it grows to fit every row the current result
 * set has (an estimated 56 px per extra row over the ~190 px base), and only
 * clamps to what the viewport actually has when the room is short. When the
 * space below the input is too small the panel flips ABOVE the field — and a
 * flipped panel is capped at the topbar's own bottom edge, read from the
 * layout's `--topbar-h` variable, so scrolling can never make the list cover
 * the navbar. The width matches the input's, so the panel reads as part of
 * the field it belongs to.
 *
 * STACKING. `z-40`: above the topbar (z-30) and every in-page panel, below the
 * mobile sidebar drawer (z-50). The old in-card version deliberately sat BELOW
 * the topbar so the list scrolled behind it; a portal panel is fixed to the
 * viewport, cannot scroll away, and must therefore simply never lose to the
 * bar. The background is opaque in both themes, so the map tiles can never
 * show through between rows.
 *
 * DISMISSAL. The parent owns the open state; this component only reports:
 * a pointer press outside both the panel and the input closes it, and the
 * parent's own Escape / selection / clear handling closes it the rest of the
 * time. Suggestion buttons use `onMouseDown={preventDefault}` so pressing one
 * never blurs the input mid-click.
 */

/**
 * The preferred panel height. It is a FLOOR on the available space, not a cap:
 * the brief asks for "enough dynamic height to display available results
 * without clipping", so the panel grows to every row when the room exists and
 * only falls back to the 190 px default when the viewport is short.
 */
const PREFERRED_HEIGHT = 190
/** Per-row height used to size the panel to its content. */
const ROW_HEIGHT = 56
/** The panel's own chrome (padding, border) plus a safety margin. */
const PANEL_CHROME = 16
/** Below this much available space the panel flips above the input. */
const MIN_BELOW = 64
/** The gap between the input's bottom edge and the panel. */
const GAP = 6
/**
 * The topbar's own height, read from the CSS variable the layout publishes.
 * A panel flipped ABOVE the input must stop at the navbar's bottom edge —
 * "while scrolling the page, suggestions must remain under the sticky navbar
 * and must not cover it" — so this is a hard ceiling, never crossed.
 */
function topbarHeight() {
  // `--topbar-h` is published in rem ("4rem"), so parse the NUMBER and convert
  // against the root font size rather than reading pixels that are not there.
  const raw = parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--topbar-h') || '4',
  )
  if (!Number.isFinite(raw)) return 64
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
  return raw * rem
}

export default function LocationSuggestions({
  inputRef,
  open,
  loading = false,
  error = null,
  suggestions = [],
  activeIndex = -1,
  onHighlight,
  onChoose,
  onClose,
  listId = 'location-suggestions',
  optionIdPrefix = 'location-suggestion',
  testIdPrefix = 'location-suggestion',
  // Optional array the caller owns; when given, each rendered option row
  // registers itself so the caller can scroll the keyboard-highlighted row
  // into view (Rainy Alerts' ArrowUp/ArrowDown does exactly that).
  optionRefs,
  // The portal panel's z-index. The default sits above the topbar (z-30) and
  // the map picker's tiles, below the sidebar drawer (z-50). A caller opened
  // INSIDE a higher overlay (the map dialog is z-50) passes a higher value so
  // the list is not painted UNDER the dialog that hosts its search field.
  zIndex = 1200,
}) {
  const [position, setPosition] = useState(null)
  const rootRef = useRef(null)
  // The CURRENT suggestion list, mirrored into a ref so `measure` can size the
  // panel to its content without `measure` becoming a dependency that re-runs
  // the layout effect (and re-attaches the listeners) on every keystroke.
  const listRef = useRef(suggestions)
  useEffect(() => {
    listRef.current = suggestions
  }, [suggestions])

  // Re-measure from the input's live viewport rectangle. Runs on open, on any
  // scroll anywhere (capture) and on resize, so the panel tracks the field.
  const measure = useCallback(() => {
    const input = inputRef?.current
    if (!input || !input.isConnected) return
    const box = input.getBoundingClientRect()
    const viewportH = window.innerHeight
    // Read fresh each measure, so the row estimate tracks the CURRENT list —
    // the caller's `suggestions` prop is not visible to this callback, and a
    // stale list would size the panel for the previous query.
    const list = Array.isArray(listRef.current) ? listRef.current : []

    const width = Math.max(box.width, 280)
    let top = box.bottom + GAP

    // DYNAMIC HEIGHT: as tall as the content needs when the room exists. The
    // measured height is only used to size the panel; `maxHeight` below still
    // clamps to what fits, so a long list scrolls inside a panel that never
    // overflows the viewport or the navbar.
    const wanted = Math.min(
      PREFERRED_HEIGHT + Math.max(list.length - 1, 0) * ROW_HEIGHT,
      viewportH - topbarHeight() - PANEL_CHROME,
    )
    let height = PREFERRED_HEIGHT

    const below = viewportH - top - 8
    if (below < MIN_BELOW) {
      // Not enough room below: flip above the field, as tall as fits there —
      // but never past the topbar's bottom edge, which is the ceiling the
      // brief sets. `belowBar` is that hard maximum.
      const belowBar = box.top - GAP - topbarHeight()
      const above = box.top - GAP - 8
      if (above >= MIN_BELOW) {
        height = Math.max(
          Math.min(wanted, above, belowBar > MIN_BELOW ? belowBar : above),
          96,
        )
        top = box.top - GAP - height
      } else {
        // Neither side fits; take what exists below and let it scroll.
        height = Math.max(Math.min(PREFERRED_HEIGHT, below), 96)
      }
    } else {
      height = Math.min(wanted, below)
    }

    // Keep the panel inside the viewport horizontally on narrow phones.
    const left = Math.min(Math.max(box.left, 8), Math.max(window.innerWidth - width - 8, 8))
    setPosition({ top, left, width, height })
  }, [inputRef])

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null)
      return undefined
    }
    measure()

    const onPointerDown = (event) => {
      if (rootRef.current?.contains(event.target)) return
      if (inputRef?.current?.contains(event.target)) return
      onClose?.()
    }

    window.addEventListener('scroll', measure, true)
    window.addEventListener('resize', measure)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('scroll', measure, true)
      window.removeEventListener('resize', measure)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open, measure, onClose, inputRef])

  // A new result set is a new height: re-measure when the list changes while
  // the panel is open, so it grows/shrinks to the content it actually shows.
  useEffect(() => {
    if (open) measure()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestions, open])

  // HOW OFTEN each name appears, so repeated branch names are shown with their
  // full branch line rather than a bare parts list. Same rule the Location
  // page has always applied; it now travels with the shared panel so both
  // screens present a chain's branches identically.
  const repeatedNameCounts = useMemo(() => {
    const counts = {}
    for (const candidate of suggestions) {
      if (candidate?.name) counts[candidate.name] = (counts[candidate.name] || 0) + 1
    }
    return counts
  }, [suggestions])

  if (!open || !position) return null

  return createPortal(
    <div
      ref={rootRef}
      id={listId}
      role="listbox"
      aria-label="Location suggestions"
      style={{
        position: 'fixed',
        top: position.top,
        left: position.left,
        width: position.width,
        maxHeight: position.height,
        zIndex,
      }}
      className="z-40 mt-0 overflow-y-auto overscroll-contain rounded-card border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-800"
    >
      {loading && suggestions.length === 0 ? (
        <p className="px-3 py-3 text-sm text-slate-500">Searching locations…</p>
      ) : error ? (
        /* THE SEARCH ITSELF FAILED. Says so, rather than showing an empty
           list, which would read as "nothing matches what you typed" - a
           different and wrong conclusion. */
        <p role="status" className="px-3 py-3 text-sm text-caution-dark dark:text-caution-light">
          {error}
        </p>
      ) : suggestions.length === 0 ? (
        <p className="px-3 py-3 text-sm text-slate-500">No matching locations found</p>
      ) : (
        suggestions.map((candidate, index) => (
          <button
            key={`${candidate.lat}-${candidate.lon}-${index}`}
            id={`${optionIdPrefix}-${index}`}
            ref={optionRefs ? (node) => { optionRefs.current[index] = node } : undefined}
            type="button"
            role="option"
            aria-selected={index === activeIndex}
            data-testid={testIdPrefix}
            className={`block w-full rounded-field px-3 py-2.5 text-left hover:bg-aqua-50 dark:hover:bg-slate-700 ${index === activeIndex ? 'bg-aqua-50 dark:bg-slate-700' : ''
              }`}
            onMouseDown={(event) => event.preventDefault()}
            onMouseEnter={() => onHighlight?.(index)}
            onClick={() => onChoose?.(candidate)}
          >
            {/* A HIT SAYS WHAT IT IS AND WHERE INSIDE THE TOWN IT IS. A
                college, a school, a shop and a bank branch all come back from
                the same box, so without this the list is a wall of
                near-identical names. When several rows share a name, the full
                branch line is shown instead of the parts list, so the branches
                of one chain are tellable apart at a glance. */}
            <span className="flex items-start justify-between gap-2">
              <span className="min-w-0">
                <span className="block break-words text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {candidate.name}
                </span>
                <span className="mt-0.5 block break-words text-xs text-slate-500 dark:text-slate-400">
                  {repeatedNameCounts[candidate.name] > 1
                    ? candidate.branch_label || candidate.label
                    : [
                      candidate.poi_label,
                      candidate.area || candidate.city,
                      candidate.district,
                      candidate.state,
                      candidate.country,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                </span>
              </span>
              {/* A postcode pins down which branch this is. */}
              {candidate.pincode && (
                <span className="mt-0.5 shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-2xs text-slate-500 dark:bg-slate-700 dark:text-slate-300">
                  {candidate.pincode}
                </span>
              )}
            </span>
          </button>
        ))
      )}
    </div>,
    document.body,
  )
}
