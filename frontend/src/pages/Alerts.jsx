import { useState } from 'react'

import { alertApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Card from '@/components/Card'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import Icon from '@/components/Icon'
import PageHeader from '@/components/PageHeader'
import Spinner from '@/components/Spinner'
import { ICONS } from '@/config/navigation'
import { useApi } from '@/hooks/useApi'
import {
  REFRESH_GROUPS,
  announceDataChanged,
  useDataRefresh,
} from '@/utils/dataRefresh'
import { errorMessage, formatDate } from '@/utils/format'

// Presentation for the server's three alert states. Kept as lookup tables
// rather than nested ternaries in the JSX so the chip cannot say one thing while
// the filter chip says another.
const STATUS_LABELS = {
  active: 'Active',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
}

const STATUS_BADGE_TONES = {
  active: 'unsafe',
  acknowledged: 'slate',
  resolved: 'safe',
}

const STATUS_FILTERS = [
  { key: undefined, label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'acknowledged', label: 'Acknowledged' },
  { key: 'resolved', label: 'Resolved' },
]

/**
 * The shared size/shape for every per-alert action button.
 *
 * The three actions (Mark read / Resolve / Reopen) are the same control and must
 * not drift apart in size, so the spacing lives here once. COLOUR is deliberately
 * NOT set here: only the UNREAD alert's "Mark read" button is the aqua one (see
 * `ALERT_ACTION_BUTTON_AQUA`), and the others keep the ordinary secondary
 * appearance. Mixing a colour into this base would repaint all three.
 */
export const ALERT_ACTION_BUTTON = 'px-2.5 py-1.5 text-xs font-medium'

/**
 * The AQUA variant, used by an UNREAD alert's "Mark read" button only.
 *
 * AN AQUA FILL WITH WHITE TEXT, in the application's own water palette, so the
 * primary action on an unread alert reads as the same family of control as the
 * filter chips and the primary buttons rather than as an alarm.
 *
 * WHY `aqua-700` AND NOT `aqua-500`/`600`. Measured with the WCAG relative-luminance
 * formula, white on this palette is:
 *
 *     aqua-500 #0e9de8  3.00   FAILS AA (needs 4.5)
 *     aqua-600 #007cc6  4.47   FAILS AA, just under the line
 *     aqua-700 #0163a0  6.38   PASSES AA
 *     aqua-800 #065384  8.15   PASSES AA (used for hover/active)
 *
 * The button is `text-xs` (12px), i.e. NORMAL-size text, so the 4.5 threshold
 * applies and the brighter aquas cannot be used with white. `aqua-700` at rest
 * and `aqua-800` when pressed/pointed-at clears the bar with room to spare.
 *
 * The `!` (Tailwind important) on each state is what makes it authoritative over
 * both the inherited black ROW hover and `.dark .card .btn-secondary` in
 * index.css — without it those rules win on specificity and repaint the label,
 * which is exactly the illegibility this avoids.
 */
export const ALERT_ACTION_BUTTON_AQUA =
  `${ALERT_ACTION_BUTTON} `
  + '!bg-aqua-700 !text-white !border-transparent '
  + 'hover:!bg-aqua-800 hover:!text-white '
  + 'active:!bg-aqua-800 active:!text-white '
  + 'focus-visible:!ring-2 focus-visible:!ring-aqua-400 focus-visible:!ring-offset-2 '
  + 'focus-visible:!ring-offset-white dark:focus-visible:!ring-offset-slate-900 '
  + 'disabled:!bg-aqua-700 disabled:!text-white disabled:!opacity-60 '
  + 'dark:!bg-aqua-700 dark:!text-white '
  + 'dark:hover:!bg-aqua-800 dark:hover:!text-white '
  + 'dark:active:!bg-aqua-800 dark:active:!text-white '
  + 'group-hover/alert:!bg-aqua-700 group-hover/alert:!text-white '
  + 'group-hover/alert:hover:!bg-aqua-800 group-hover/alert:hover:!text-white '

export default function Alerts() {
  const [statusFilter, setStatusFilter] = useState(undefined)
  const [busyId, setBusyId] = useState(null)
  const [actionError, setActionError] = useState(null)
  // A locally-adjusted copy of the counters, used only between a user action and
  // the refetch that follows it. `null` means "trust the server" — the normal
  // state — and it is cleared as soon as the request settles.
  const [summaryOverride, setSummaryOverride] = useState(null)

  const summary = useApi(() => alertApi.summary(), [])
  const list = useApi(() => alertApi.list({ status: statusFilter }), [statusFilter])

  // The backend raises an alert for every unsafe prediction, so an unsafe
  // submission must show up here without a manual reload.
  useDataRefresh(REFRESH_GROUPS.alerts, () => {
    list.refetch()
    summary.refetch()
  })

  const rows = list.data?.data || []
  const counters = summaryOverride ?? summary.data?.data ?? {}
  const unreadCount = counters.active ?? counters.unread ?? 0

  async function act(alertId, action) {
    setBusyId(alertId)
    setActionError(null)

    // --- Optimistic local update -----------------------------------------
    // The count the user is watching is the badge in the topbar, and it is fed by
    // `summary`. Refetching alone leaves a visible gap between the press and the
    // new number, which reads as the button having done nothing. So the rows and
    // the counters are adjusted here FIRST, and the refetch below is what makes
    // the server the authority again a moment later.
    //
    // Only the two transitions that actually reduce the count are applied:
    // marking read and resolving both move an alert out of `active`. If the
    // server disagrees, the refetch overwrites this with the truth.
    const wasActive = rows.find((row) => row.id === alertId)?.is_read === false
    if (wasActive) {
      setSummaryOverride((previous) => {
        const base = previous ?? counters
        const next = { ...base }
        // `active` is what the bell badge reads; `unread` is what the tiles show.
        next.active = Math.max(0, (next.active ?? 0) - 1)
        next.unread = Math.max(0, (next.unread ?? 0) - 1)
        next.read = (next.read ?? 0) + 1
        next.acknowledged = (next.acknowledged ?? 0) + 1
        return next
      })
    }

    try {
      if (action === 'Mark read') await alertApi.markRead(alertId)
      else if (action === 'Reopen') await alertApi.unresolve(alertId)
      else await alertApi.resolve(alertId)
      await Promise.all([list.refetch(), summary.refetch()])
      // The server has answered, so the optimistic figures are no longer needed.
      setSummaryOverride(null)
      // Tell the shell the unread set changed, so the bell badge in the topbar
      // and the counter on the sidebar link both re-read the count. Refetching
      // only this page's `summary` updated the tiles below while leaving the
      // badge stale — the number the user was watching never moved.
      announceDataChanged(REFRESH_GROUPS.alerts)
    } catch (err) {
      // Surfaced rather than swallowed: a failed update that silently does
      // nothing looks like the button is broken, and the user retries forever.
      // The optimistic override is dropped too, so the count returns to whatever
      // the server last said rather than keeping a number that never happened.
      setSummaryOverride(null)
      setActionError(errorMessage(err, 'That change could not be saved. Please try again.'))
    } finally {
      setBusyId(null)
    }
  }

  async function markAllRead() {
    setBusyId('all')
    setActionError(null)
    try {
      await alertApi.markAllRead()
      // Marking everything read moves every open alert out of `active` at once.
      // The badge is set to zero straight away rather than waiting for the
      // round trip, because "mark all as read" is the one action whose result
      // the user already knows.
      setSummaryOverride((previous) => {
        const base = { ...(previous ?? counters) }
        base.active = 0
        base.unread = 0
        base.read = base.total ?? 0
        return base
      })
      await Promise.all([list.refetch(), summary.refetch()])
      setSummaryOverride(null)
      announceDataChanged(REFRESH_GROUPS.alerts)
    } catch (err) {
      setSummaryOverride(null)
      setActionError(errorMessage(err, 'Could not mark all alerts as read.'))
    } finally {
      setBusyId(null)
    }
  }

  const tiles = [
    { label: 'Unread', value: counters.unread },
    { label: 'Read', value: counters.read },
    { label: 'Total', value: counters.total },
  ]

  return (
    <div>
      <PageHeader
        breadcrumb="Monitoring"
        title="Alerts"
        description="Unsafe water detections and system notifications."
      />

      {/* THREE-UP ON A PHONE TOO.

          `grid-cols-3` from the start (not `sm:grid-cols-3`) keeps Unread / Read
          / Total on ONE ROW at 390px instead of stacking into three tall cards
          that push the alerts below the fold. `gap-2` on mobile tightens the
          spacing so the three fit; `sm:gap-4` restores the roomier desktop gap.

          The bottom hint line ("Needs your attention" and friends) is REMOVED:
          on a phone it was a third line of small text in each card, and it said
          nothing the label and number had not already said. */}
      <div className="grid mb-6 grid-cols-3 gap-2 sm:gap-4">
        {tiles.map((tile) => (
          <div key={tile.label} className="card card-interactive p-3 sm:p-5">
            <p className="text-2xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300">
              {tile.label}
            </p>
            <p className="mt-2 text-xl font-semibold leading-none tracking-tight text-slate-900 tabular sm:mt-2.5 sm:text-[1.75rem] dark:text-white">
              {summary.loading ? '—' : tile.value ?? 0}
            </p>
          </div>
        ))}
      </div>

      {actionError && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-card border-unsafe-light bg-unsafe-light/50 px-3.5 py-3 text-sm text-unsafe-dark"
        >
          <Icon path={ICONS.info} className="mt-0.5 h-4 w-4 shrink-0" />
          {actionError}
        </div>
      )}

      {/* ONE ALIGNED ROW (prompt 3). On `sm:` up the Show/chips group and the
          "Mark all as read" button share a single flex row: the chips take the
          natural space they need and the button is pushed to the FAR RIGHT by
          `justify-between`, vertically centred by `items-center`. Below `sm:`
          the two stack (`flex-col` with a clean gap), so nothing overlaps or
          clips on a phone. Wrapping is enabled so a very narrow desktop/tablet
          width that genuinely cannot fit both wraps cleanly rather than
          overlapping. */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-4">
        {/* ONE ROW ON A PHONE. `flex-nowrap` keeps "Show" and all four status
            chips on a single line; the chips are SMALL (`px-2 py-1 text-2xs`) so
            they fit across 390px, and each takes an equal share (`flex-1`) so
            they come out evenly sized rather than sized to their label. From
            `sm:` up they return to the roomier padding for a mouse, and sit
            alongside the bulk action instead of above it. */}
        <div className="flex min-w-0 flex-nowrap items-center gap-1.5 sm:flex-1 sm:flex-wrap sm:gap-3">
          <span className="hidden shrink-0 text-xs font-semibold uppercase tracking-wider text-slate-500 sm:inline dark:text-slate-300">
            Show
          </span>
          {STATUS_FILTERS.map((filter) => (
            <button
              key={filter.label}
              type="button"
              onClick={() => setStatusFilter(filter.key)}
              aria-pressed={statusFilter === filter.key}
              className={`min-w-0 flex-1 truncate rounded-full px-2 py-1 text-2xs font-medium transition-colors sm:flex-none sm:px-4 sm:py-2 sm:text-xs ${
                statusFilter === filter.key
                  ? 'bg-aqua-600 text-white shadow-sm dark:bg-aqua-700'
                  : 'bg-slate-100 text-slate-600 hover:bg-black hover:text-white dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-black dark:hover:text-white'
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>

        {unreadCount > 0 && (
          <div className="shrink-0">
            <Button
              variant="secondary"
              className="whitespace-nowrap"
              loading={busyId === 'all'}
              onClick={markAllRead}
              icon={<Icon path={ICONS.check} className="h-4 w-4" />}
            >
              Mark all as read
            </Button>
          </div>
        )}
      </div>

      <Card padded={false}>
        {list.loading ? (
          <Spinner label="Loading alerts…" />
        ) : list.error ? (
          <div className="p-5">
            <ErrorState message={list.error} onRetry={list.refetch} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title="No alerts"
            description="When a prediction comes back unsafe, an alert is raised here with the readings that triggered it."
            icon={<Icon path={ICONS.alerts} className="h-7 w-7" />}
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.map((alert) => (
              <li
                key={alert.id}
                // Hover is BLACK with white text, in both themes.
                //
                // The card used to lift to `slate-50/60` — a near-white wash on
                // a near-white card — so a pointer over an alert produced almost
                // no visible change and read as "this row is not interactive".
                // Black is the unambiguous opposite of the white card surface,
                // and `hover:text-white` (applied to the row, so the message and
                // the meta line inherit it) keeps every word legible on it.
                className="group/alert flex flex-col gap-3 px-5 py-4 transition-colors hover:bg-black hover:text-white dark:hover:bg-black dark:hover:text-white sm:flex-row sm:items-start"
              >
                <span
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-field ${
                    alert.status === 'active'
                      ? 'bg-unsafe-light text-unsafe-dark'
                      : alert.status === 'resolved'
                        ? 'bg-safe-light text-safe-dark'
                        : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                  }`}
                  aria-hidden="true"
                >
                  <Icon path={ICONS.alerts} className="h-4 w-4" />
                </span>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {/* Driven by `status`, not `is_read`: the server
                        distinguishes active / acknowledged / resolved, and the
                        chip has to say which one it is or the resolved filter
                        and the chip would disagree. */}
                    <Badge tone={STATUS_BADGE_TONES[alert.status] || 'slate'}>
                      {STATUS_LABELS[alert.status] || 'Active'}
                    </Badge>
                    <span className="text-xs text-slate-400 tabular group-hover/alert:text-white">
                      {formatDate(alert.created_at)}
                    </span>
                    {alert.resolved_at && (
                      <span className="text-xs text-slate-400 tabular group-hover/alert:text-white">
                        · resolved {formatDate(alert.resolved_at)}
                      </span>
                    )}
                  </div>
                  {/* `group-hover/alert:text-white` beats the dark-card colour
                      remap in index.css, so the message really does turn white
                      on the black hover rather than staying slate-200. */}
                  <p className="mt-1.5 text-sm leading-relaxed text-slate-700 group-hover/alert:text-white dark:text-slate-200">
                    {alert.message}
                  </p>
                </div>

                <div className="flex shrink-0 flex-wrap gap-2 sm:pl-2">
                  {/* The actions are a function of the alert's actual status, so
                      a resolved alert offers only its undo. Showing "Resolve" on
                      something already resolved was half the reason the button
                      looked broken — there was nothing left for it to do. */}
                  {alert.status === 'resolved' ? (
                    <Button
                      variant="secondary"
                      loading={busyId === alert.id}
                      onClick={() => act(alert.id, 'Reopen')}
                      className={ALERT_ACTION_BUTTON}
                    >
                      Reopen
                    </Button>
                  ) : (
                    <>
                      {alert.status === 'active' && (
                        <Button
                          variant="secondary"
                          loading={busyId === alert.id}
                          onClick={() => act(alert.id, 'Mark read')}
                          className={ALERT_ACTION_BUTTON_AQUA}
                        >
                          Mark as Read
                        </Button>
                      )}
                      <Button
                        variant="secondary"
                        loading={busyId === alert.id}
                        onClick={() => act(alert.id, 'Resolve')}
                        className={ALERT_ACTION_BUTTON}
                      >
                        Resolve
                      </Button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
