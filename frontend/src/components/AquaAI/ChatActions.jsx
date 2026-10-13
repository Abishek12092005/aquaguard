/**
 * The controls that belong to one assistant turn.
 *
 * A reply can end with real, clickable actions: "here are your unsafe reports"
 * followed by the two buttons that export them, or a link straight to the screen
 * the answer is about. They are rendered as CHILDREN OF THE MESSAGE rather than as
 * a floating bar, so each set of controls stays attached to the answer it belongs
 * to as the conversation grows.
 *
 * WHAT THE ASSISTANT CAN AND CANNOT ASK FOR. It sends one of exactly two action
 * types, and both are closed vocabularies:
 *
 *   DOWNLOAD_REPORTS  { scope: all|safe|moderate|unsafe, format: csv|pdf }
 *   NAVIGATE          { target: one of this app's own routes }
 *
 * There is no URL, no path and no filename in either one. The download is built
 * here in the browser from data re-fetched from the API, and a navigation target
 * is checked against the same allow-list the rest of the panel uses — so a
 * malformed or unexpected action renders nothing rather than doing something
 * unplanned.
 */

import Button from '@/components/Button'
import Icon from '@/components/Icon'
import { ROUTES } from '@/utils/constants'
import { useNavigate } from 'react-router-dom'

// The routes the assistant is allowed to point at. `/login`, `/register`,
// `/profile` and `/admin` are deliberately absent, so a navigation action can
// never send a visitor to a screen that does not exist or to the console.
const ROUTE_LABELS = {
  [ROUTES.home]: 'Home',
  [ROUTES.dashboard]: 'Dashboard',
  [ROUTES.predict]: 'Manual Prediction',
  [ROUTES.history]: 'Prediction History',
  [ROUTES.alerts]: 'Alerts',
  [ROUTES.reports]: 'Reports',
  [ROUTES.location]: 'Location Prediction',
  [ROUTES.rainyAlerts]: 'Rainy Alerts',
}

/** Icon path for a download action, matched to the format. */
const FORMAT_ICONS = {
  pdf: 'M6 9V3h12v6M6 18H4v-6h16v6h-2M6 14h12v7H6z',
  csv: 'M12 3v12m0 0 4-4m-4 4-4-4M4 19h16',
}

function actionKey(action, index) {
  return `${action.type}-${action.format || action.target || index}-${index}`
}

export default function ChatActions({ actions, onDownload }) {
  const navigate = useNavigate()
  if (!Array.isArray(actions) || actions.length === 0) return null

  // Only render the types this component understands. An unknown type is dropped
  // rather than rendered as a dead button.
  const downloads = actions.filter(
    (a) => a?.type === 'DOWNLOAD_REPORTS' && (a.format === 'csv' || a.format === 'pdf'),
  )
  const navigations = actions.filter(
    (a) => a?.type === 'NAVIGATE' && ROUTE_LABELS[a.target],
  )

  if (downloads.length === 0 && navigations.length === 0) return null

  /** Human wording for the slice a download covers. */
  const scopeWord = (scope) =>
    !scope || scope === 'all' ? '' : `${scope} `

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      {navigations.map((action, index) => (
        <button
          key={actionKey(action, index)}
          type="button"
          onClick={() => navigate(action.target)}
          className="inline-flex items-center gap-1.5 rounded-field border border-aqua-200 bg-aqua-50 px-2.5 py-1.5 text-2xs font-medium text-aqua-700 transition-colors hover:bg-aqua-100 dark:border-aqua-700 dark:bg-aqua-900/40 dark:text-aqua-200 dark:hover:bg-aqua-900/70"
        >
          <Icon path="M9 6l6 6-6 6" className="h-3 w-3" strokeWidth={2.4} />
          {ROUTE_LABELS[action.target]}
        </button>
      ))}

      {downloads.map((action, index) => (
        <Button
          key={actionKey(action, index)}
          type="button"
          onClick={() => onDownload?.(action)}
          aria-label={`Download ${scopeWord(action.scope)}reports as ${action.format.toUpperCase()}`}
          // A compact pill: the black-at-rest / blue-on-hover treatment used by
          // the Reports screen's own download buttons, so the same action looks
          // the same in both places.
          className="min-w-0 bg-black px-2.5 py-1.5 text-2xs text-white hover:bg-aqua-500 hover:text-white active:bg-aqua-600 dark:bg-black dark:text-white dark:hover:bg-aqua-500 dark:hover:text-white"
        >
          <Icon path={FORMAT_ICONS[action.format]} className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">
            {action.format === 'pdf' ? 'Download PDF' : 'Download CSV'}
          </span>
        </Button>
      ))}
    </div>
  )
}