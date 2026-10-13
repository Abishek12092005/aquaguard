/**
 * Standard page header.
 *
 * Every screen uses this so titles, descriptions and action placement are
 * consistent. Without it each page invents its own spacing and the app looks
 * assembled rather than designed.
 */
export default function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
  // Optional override for the overline's colour. PageHeader's default aqua is
  // right almost everywhere; the Dashboard wants it WHITE, so the class is
  // passed in rather than the component guessing which screen it is on.
  breadcrumbClassName = '',
  className = '',
  // `oneLine` clamps the description to a SINGLE line (ellipsis on overflow).
  // The default is that the description WRAPS IN FULL, which is correct for a
  // screen whose paragraph is a short sentence. Pass `oneLine` where the text is
  // long enough that wrapping it to three lines pushes the page content down.
  oneLine = false,
  // `fullWidth` lets the description take the WHOLE row (it wraps onto the next
  // line) rather than being capped at half the width beside the action button.
  // Used where the sentence is short enough to read as one full line.
  fullWidth = false,
  // `stacked` puts the actions on the line BELOW the heading — but ONLY on a
  // phone. From `sm:` up the header goes back to the default row with the
  // action hard right, so the desktop layout is unchanged.
  //
  // This is the exception, not the rule: every other screen keeps the
  // heading-left / action-right row at all widths. Home passes it because the
  // greeting is a long, variable-length sentence, so on a phone the button
  // squeezed up against it; giving the button its own line (plus "startButton"
  // spacing, see below) separates the two. The desktop row has room for both,
  // so nothing needs to move there.
  stacked = false,
}) {
  return (
    // `flex` was missing here, so `flex-col`/`sm:flex-row` had no effect and the
    // header never actually laid out as a row on desktop. It is the single
    // biggest reason page headers looked misaligned next to their action button.
    //
    // THE ACTION SITS ON THE SAME LINE AS THE TITLE, hard against the right
    // edge. `sm:items-start` (not `sm:items-center`) is what puts the title and
    // the button on one baseline: the title block is the taller of the two, so
    // top-aligning them makes the button's top edge meet the title's top edge
    // rather than floating in the middle of the description. The button may
    // still carry its own `pt-*` when a page wants it nudged down a line.
    //
    // `className` is forwarded so a page can drop its header on paper
    // (`print:hidden`) without the component having to know about printing.
    //
    // THE ROW APPLIES AT EVERY WIDTH, PHONE INCLUDED. It used to be
    // `flex-col ... sm:flex-row`, so BELOW `sm` the title and the button stacked
    // vertically and the control sat underneath the heading. The requirement is
    // the opposite on a phone: the action belongs on the SAME LINE as the
    // heading, hard right — Location's "Find my location", Profile's "Log out"
    // and the Dashboard's "New prediction" all read as belonging to their title
    // rather than as a block that happens to follow it.
    //
    // `items-start` keeps both on the title's top edge, and `justify-between`
    // pushes the action to the right edge on every viewport.
    //
    // `stacked` OVERRIDES THE ROW ON A PHONE ONLY: below `sm` the header becomes
    // a column (title, then the action on the next line, pushed to the left
    // edge) and from `sm:` up the classes fall back to the standard row. So the
    // same page can stack on mobile and stay a right-aligned row on desktop.
    <div
      className={`mb-6 flex gap-3 sm:gap-4 ${stacked
          ? 'flex-col items-stretch sm:flex-row sm:items-start sm:justify-between'
          : 'flex-row items-start justify-between'
        } ${className}`}
    >
      {/* The title block is capped at half the row so a WRAPPING description has
          a tidy column beside the action buttons. With `oneLine` or `fullWidth`
          the cap is dropped: the block then fills the row, which is what lets a
          single line stay on one line instead of truncating immediately. */}
      <div
        className={`min-w-0 ${
          oneLine || fullWidth ? 'flex-1' : 'sm:max-w-[50%]'
        }`}
      >
        {breadcrumb && (
          <p
            className={`mb-1.5 text-2xs font-semibold uppercase tracking-wider ${breadcrumbClassName || 'text-aqua-600 dark:text-aqua-300'}`}
          >
            {breadcrumb}
          </p>
        )}
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">
          {title}
        </h2>
        {description && (
          // THE DESCRIPTION WRAPS IN FULL — NO ELLIPSIS, NO "...".
          //
          //  `hidden sm:block` keeps it off a phone, where the header would
          //     otherwise push the content below the fold. That stays: the
          //     requirement is that the HEADING and the BUTTON share the row on
          //     mobile, not that the paragraph comes back.
          //
          //  Unless `oneLine` is set, the paragraph WRAPS IN FULL: the title
          //     block is capped at half the header width, so it wraps onto two or
          //     three tidy lines beside the action buttons. With `oneLine` it is
          //     clamped to a single line (`truncate`) and the block takes the
          //     whole row, so Predict and History state their purpose on ONE line.
          <p
            className={`mt-1.5 hidden text-sm leading-relaxed text-slate-500 sm:block dark:text-slate-300 ${
              oneLine ? 'truncate' : ''
            }`}
            title={oneLine ? description : undefined}
          >
            {description}
          </p>
        )}
      </div>

      {/* THE ACTIONS SIT AT THE FAR RIGHT OF THE SAME ROW AS THE HEADING.

          `sm:items-start` on the parent aligns the button row's top edge with
          the title's, and `sm:justify-between` pushes this block to the right,
          so every page's primary control (New prediction, Find my location,
          download buttons) lines up level with its heading on the right — the
          "button straight to the right of the heading" the requirement asks for. */}
      {actions && (
        // `shrink-0` so the actions never get squeezed by a long title, and
        // `justify-end` so they hug the right edge on every viewport. Pages can
        // still shrink the individual buttons on mobile with their own classes.
        // `justify-start` on a phone pairs with `stacked` above, so the button
        // sits at the LEFT edge under the title; `sm:justify-end` restores the
        // right-aligned desktop row.
        <div
          className={`flex flex-wrap items-center gap-2 ${stacked
              ? 'justify-start sm:justify-end'
              : 'shrink-0 justify-end'
            }`}
        >
          {actions}
        </div>
      )}
    </div>
  )
}
