/**
 * Inline loading indicator with an accessible label.
 *
 * A droplet landing in still water: the drop falls, then two rings ripple out
 * from where it hit. Three elements on one shared cycle, so it reads as a
 * single event rather than three unrelated animations — which is what the old
 * spinning ring was.
 */
export default function Spinner({ label = 'Loading…', size = 'md', className = '' }) {
  const small = size === 'sm'
  const drop = small ? 'h-1.5 w-1.5' : 'h-2.5 w-2.5'
  const ring = small ? 'h-3.5 w-3.5' : 'h-6 w-6'
  const ringDelay = small ? '1.4s' : '1.5s'

  return (
    <div className={`flex items-center justify-center gap-3 py-8 ${className}`} role="status">
      <span className={`relative flex items-center justify-center ${small ? 'h-4 w-4' : 'h-8 w-8'}`} aria-hidden="true">
        {/* The falling drop. */}
        <span className={`absolute ${drop} rounded-full bg-aqua-600 motion-safe:animate-drop-bounce`} />
        {/* Two ripples, the second offset by half a beat so the water keeps
            moving between drops instead of pausing. */}
        <span className={`absolute ${ring} rounded-full border-aqua-400/70 motion-safe:animate-ripple`} />
        <span
          className={`absolute ${ring} rounded-full border-aqua-400/70 motion-safe:animate-ripple`}
          style={{ animationDelay: ringDelay }}
        />
      </span>
      <span className="text-sm text-slate-500">{label}</span>
    </div>
  )
}
