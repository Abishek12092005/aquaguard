/**
 * Surface container used for every panel and grouped block of content.
 *
 * `padded={false}` drops the body padding for content that should reach the
 * card's edges (tables, divided lists) while keeping the header aligned with the
 * page's other cards. That is why the header carries its own horizontal padding
 * in that mode rather than the whole card doing so.
 */
export default function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
  bodyClassName = '',
  padded = true,
  // Forwarded onto the <section>, so a caller can drive an entry animation's
  // `animationDelay` inline — the class is what animates, this is only the
  // stagger. Without it a row of cards would all fly in on the same frame.
  style,
}) {
  const hasHeader = Boolean(title || actions)

  return (
    // `overflow-hidden` clips the card's own children to its rounded corners.
    //
    // Without it, a child that is wider than the card — the history table, which
    // has more columns than fit at once — painted straight past the card's
    // rounded edge and its shadow, so the table appeared to "come out of the
    // white box". The table still scrolls horizontally (`.table-wrap` owns that);
    // this only guarantees the scroll happens *inside* the card's bounds.
    <section
      className={`card overflow-hidden ${padded ? '' : 'p-0'} ${className}`}
      style={style}
    >
      {hasHeader && (
        <header
          className={`flex flex-wrap items-start justify-between gap-x-4 gap-y-2 ${
            padded ? 'mb-4' : 'px-5 pb-3 pt-5'
          }`}
        >
          <div className="min-w-0 flex-1">
            {title && (
              <h2 className="text-[0.9375rem] font-semibold leading-6 text-slate-900">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
          </div>
          {actions && (
            <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
          )}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}
