/** Placeholder shown when a list has no rows yet. */
export default function EmptyState({ title = 'Nothing here yet', description, action, icon }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon ? (
        <div className="text-aqua-400">{icon}</div>
      ) : (
        <div
          className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-aqua-50 text-aqua-600 ring-1 ring-inset ring-aqua-100"
          aria-hidden="true"
        >
          <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" stroke="currentColor" strokeWidth="1.8">
            <path d="M12 3c4 5 6 8 6 11a6 6 0 0 1-12 0c0-3 2-6 6-11Z" strokeLinecap="round" />
          </svg>
        </div>
      )}
      <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
      {description && (
        <p className="max-w-sm text-sm leading-relaxed text-slate-500">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
