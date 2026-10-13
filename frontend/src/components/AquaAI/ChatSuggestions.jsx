/**
 * Starting suggestions shown in an empty chat.
 *
 * The sets live in `suggestions.js` so this file exports only a component, and
 * they change with the screen the user is on. Each suggestion is plain text
 * submitted through the same path a typed message takes — none of them maps to
 * a canned or pre-written reply.
 *
 * The buttons are real `<button type="button">` elements, so they are reachable
 * by keyboard and announced as controls, and clicking one sends the question
 * immediately rather than only filling the composer.
 */

import Icon from '@/components/Icon'
import { suggestionsFor } from '@/components/AquaAI/suggestions'
import { ICONS } from '@/config/navigation'

/** Copy that matches what the current screen can actually answer. */
const PROMPT = {
  dashboard: 'Ask about your dashboard, readings or alerts.',
  prediction: 'Ask about the parameters, or how the model works.',
  prediction_result: 'Ask about the result you just got.',
  history: 'Ask about your recorded predictions.',
  alerts: 'Ask about your alerts or latest reading.',
  general: 'Ask about your water readings, or say what you would like to open.',
}

export default function ChatSuggestions({ onPick, disabled = false, context }) {
  const suggestions = suggestionsFor(context)

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {PROMPT[context] || PROMPT.general}
      </p>
      <div className="flex flex-col gap-1.5">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion.label}
            type="button"
            disabled={disabled}
            onClick={() => onPick(suggestion.label)}
            className="flex w-full items-center gap-2.5 rounded-field border-slate-200 bg-white px-3 py-2 text-left text-xs font-medium text-slate-700 shadow-sm transition-all hover:border-aqua-300 hover:bg-aqua-50 hover:text-aqua-800 hover:shadow disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:hover:border-aqua-500 dark:hover:bg-black dark:hover:text-white"
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-aqua-50 text-aqua-600 dark:bg-aqua-900/60 dark:text-aqua-300">
              <Icon path={suggestion.icon} className="h-3.5 w-3.5" />
            </span>
            <span className="min-w-0 flex-1">{suggestion.label}</span>
            <Icon
              path={ICONS.chevronRight}
              className="h-3.5 w-3.5 shrink-0 text-slate-300 dark:text-slate-600"
            />
          </button>
        ))}
      </div>
    </div>
  )
}
