import Icon from '@/components/Icon'
import Spinner from '@/components/Spinner'
import { ICONS } from '@/config/navigation'
import { formatDate } from '@/utils/format'

/**
 * The conversation list, shown in place of the messages while history is open.
 *
 * Reads the account's own threads from `GET /ai/conversations` and lets the user
 * reopen one. Deliberately read-only apart from "open" and "new chat": deletion
 * exists on the API but is not offered here, because a list where a mis-tap
 * destroys a conversation is a list the user stops opening.
 *
 * The panel is presentational — every action is a callback into `AquaAIButton`,
 * which owns the state.
 */
export default function ChatHistory({ conversations, loading, onPick, onNewChat }) {
  const items = conversations || []

  return (
    <div className="flex-1 overflow-y-auto overscroll-contain" aria-label="Chat history">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5 dark:border-slate-700">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Past conversations
        </p>
        <button
          type="button"
          onClick={onNewChat}
          className="rounded-field px-2.5 py-1.5 text-xs font-medium text-aqua-700 transition-colors hover:bg-aqua-50 dark:text-aqua-300 dark:hover:bg-black dark:hover:text-white"
        >
          + New chat
        </button>
      </div>

      {loading ? (
        <Spinner label="Loading conversations…" />
      ) : items.length === 0 ? (
        <div className="px-4 py-10 text-center">
          <span
            className="mx-auto flex h-10 w-10 items-center justify-center rounded-field bg-aqua-50 text-aqua-600 dark:bg-slate-800 dark:text-aqua-300"
            aria-hidden="true"
          >
            <Icon path={ICONS.history} className="h-5 w-5" />
          </span>
          <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">
            No past conversations
          </p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Threads you start with Aqua AI are kept here, so you can come back to an
            answer later.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onPick(item.id)}
                className="flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors hover:bg-aqua-50/70 dark:hover:bg-black/60 dark:hover:text-white"
              >
                {/* Falls back through the likely title fields rather than
                    rendering "undefined" for a thread the server has not
                    summarised. */}
                <span className="line-clamp-2 text-sm font-medium text-slate-800 dark:text-slate-100">
                  {item.title || item.summary || item.subject || 'Untitled conversation'}
                </span>
                <span className="flex items-center gap-2 text-xs text-slate-400">
                  <span className="tabular">{formatDate(item.created_at)}</span>
                  {item.message_count != null && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span className="tabular">
                        {item.message_count} message{item.message_count === 1 ? '' : 's'}
                      </span>
                    </>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
