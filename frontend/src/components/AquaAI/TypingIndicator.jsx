/**
 * Typing indicator shown while Aqua AI is composing a reply.
 *
 * Three dots with a staggered bounce. It is a presentational signal only — the
 * real state lives in the panel. Marked `aria-live` so a screen reader
 * announces that a reply is coming rather than leaving silence.
 */
export default function TypingIndicator({ label = 'Aqua AI is thinking' }) {
  return (
    <div
      className="flex items-center gap-2"
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      <span className="flex items-center gap-1 rounded-2xl rounded-bl-sm bg-slate-100 px-3 py-2.5 dark:bg-slate-800">
        {[0, 1, 2].map((index) => (
          <span
            key={index}
            className="h-1.5 w-1.5 animate-typing-dot rounded-full bg-slate-400 dark:bg-slate-500"
            // Staggered so the dots travel rather than pulse in unison.
            style={{ animationDelay: `${index * 0.16}s` }}
            aria-hidden="true"
          />
        ))}
      </span>
      <span className="sr-only">{label}…</span>
    </div>
  )
}
