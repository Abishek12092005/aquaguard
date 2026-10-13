/** Inline failure panel with an optional retry action. */
export default function ErrorState({ title = 'Something went wrong', message, onRetry }) {
  return (
    <div
      className="flex flex-col items-center gap-2 rounded-card border-unsafe-light bg-unsafe-light/40 px-6 py-8 text-center"
      role="alert"
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-unsafe shadow-sm dark:bg-slate-900 dark:text-unsafe-light" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth="2">
          <path d="M12 8v5m0 3h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" strokeLinecap="round" />
        </svg>
      </div>
      <h3 className="text-sm font-semibold text-unsafe-dark dark:text-unsafe-light">{title}</h3>
      {message && <p className="max-w-md text-sm text-slate-600 dark:text-slate-300">{message}</p>}
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-secondary mt-3">
          Try again
        </button>
      )}
    </div>
  )
}
