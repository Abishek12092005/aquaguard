/**
 * One chat message.
 *
 * User turns sit on the right in the brand colour; Aqua AI turns on the left in
 * a neutral surface, with an avatar so the speaker is identifiable at a glance
 * rather than only by alignment.
 *
 * A failed assistant turn renders with a Retry control instead of disappearing:
 * silently dropping the message would leave the user unsure whether it was ever
 * sent, and re-typing is a worse answer than offering to try again.
 */

import ChatActions from '@/components/AquaAI/ChatActions'
import Icon from '@/components/Icon'
import { ICONS } from '@/config/navigation'
import { formatTime } from '@/utils/format'

function Avatar() {
  return (
    <span
      className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-aqua-500 to-aqua-700 text-white shadow-sm ring-1 ring-white/20 dark:from-aqua-300 dark:to-aqua-400 dark:text-aqua-900 dark:ring-white/30"
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
        <path d="M12 3c4 5 6 8 6 11a6 6 0 0 1-12 0c0-3 2-6 6-11Z" />
      </svg>
    </span>
  )
}

export default function ChatMessage({ message, onRetry, onDownload }) {
  const isUser = message.role === 'user'
  const failed = message.status === 'error'
  // Not every failure is worth retrying. "No provider is configured" is a
  // server-side setup problem: offering Retry invites the user to click a
  // button that cannot possibly succeed. Retry is reserved for transient
  // problems, where trying again genuinely can work.
  const retryable = failed && message.retryable !== false

  return (
    <div className={`flex gap-2 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && <Avatar />}

      <div className={`flex max-w-[82%] flex-col ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`whitespace-pre-wrap break-words rounded-panel px-3.5 py-2.5 text-sm leading-relaxed shadow-sm ${isUser
              ? 'rounded-br-md bg-aqua-600 text-white'
              : failed
                ? 'rounded-bl-md border-unsafe-light bg-unsafe-light/40 text-unsafe-dark dark:border-unsafe-dark dark:bg-unsafe-dark/30 dark:text-unsafe-light'
                : 'rounded-bl-md border-slate-200/70 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100'
            }`}
        >
          {message.content}
        </div>

        {/* The controls for THIS reply, directly under it: report download
            buttons and/or a link to the screen the answer is about. Rendered
            only for assistant turns - a user's own message never carries
            actions. */}
        {!isUser && !failed && (
          <ChatActions actions={message.actions} onDownload={onDownload} />
        )}

        <div className="mt-1 flex items-center gap-2 px-1">
          <time
            className="text-2xs text-slate-400 tabular dark:text-slate-500"
            dateTime={message.at?.toISOString?.() ?? undefined}
          >
            {message.at ? formatTime(message.at) : ''}
          </time>

          {retryable && onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-medium text-aqua-700 transition-colors hover:bg-aqua-50 dark:text-aqua-300 dark:hover:bg-aqua-900/50"
            >
              <Icon path={ICONS.refresh} className="h-3 w-3" />
              Retry
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
