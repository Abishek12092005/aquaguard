import Spinner from '@/components/Spinner'
import ErrorState from '@/components/ErrorState'

/**
 * KPI tile for the dashboard.
 *
 * Handles its own loading and error presentation so a single failing metric
 * degrades in place instead of blanking the whole dashboard.
 */
export default function StatCard({
  label,
  value,
  hint,
  tone = 'aqua',
  loading,
  error,
  onRetry,
  icon,
  // `className` / `style` are forwarded so a caller can supply an entry
  // animation and its stagger. They default to the tile's own gentle fade, so
  // every existing call site keeps the behaviour it had.
  className = 'animate-fade-in',
  style,
}) {
  const toneClasses = {
    aqua: 'bg-aqua-50 text-aqua-700',
    safe: 'bg-safe-light text-safe-dark',
    moderate: 'bg-caution-light text-caution-dark',
    unsafe: 'bg-unsafe-light text-unsafe-dark',
    slate: 'bg-slate-100 text-slate-600',
  }

  if (error) {
    return (
      <div className="card">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <ErrorState title="Could not load" message={error} onRetry={onRetry} />
      </div>
    )
  }

  return (
    <div className={`card card-interactive ${className}`} style={style}>
      <div className="flex items-start justify-between gap-3">
        {/* Label first, then the value — the eye lands on the number, and the
            label sits close enough above it to read as its caption. */}
        <p className="text-2xs font-semibold uppercase tracking-wider text-slate-500">
          {label}
        </p>
        {icon && (
          <span
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-field ${toneClasses[tone] || toneClasses.aqua}`}
            aria-hidden="true"
          >
            {icon}
          </span>
        )}
      </div>

      {loading ? (
        <Spinner label="Loading…" size="sm" className="!justify-start !py-3" />
      ) : (
        <>
          <p className="mt-2.5 text-[1.75rem] font-semibold leading-none tracking-tight text-slate-900 tabular">
            {value ?? '—'}
          </p>
          {hint && <p className="mt-2 text-xs text-slate-500">{hint}</p>}
        </>
      )}
    </div>
  )
}
