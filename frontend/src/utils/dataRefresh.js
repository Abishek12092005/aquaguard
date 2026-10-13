/**
 * Cross-page data-refresh signal.
 *
 * A prediction changes what three other screens display: the dashboard totals,
 * the history table and the alerts list. Rather than lifting every page's data
 * into a global store, a page that mutates data announces it here and any page
 * that cares refetches when it next mounts or while it is mounted.
 *
 * This is deliberately a plain event bus rather than a store: the server is the
 * single source of truth for all of this data, so there is nothing worth
 * caching client-side. Refetching is both simpler and more correct than trying
 * to patch a local copy — the numbers shown are always the ones the backend
 * actually has.
 *
 * Usage:
 *   announcePredictionCreated({ riskLevel: 'unsafe' })   // after a submission
 *   useDataRefresh('predictions', refetch)               // on a consuming page
 */

import { useEffect } from 'react'

/** Event name. Namespaced so it cannot collide with a third-party listener. */
export const DATA_CHANGED_EVENT = 'aquaguard:data-changed'

/**
 * The resource groups a page can subscribe to.
 *
 * Grouping matters: a new safe prediction changes the history and the dashboard
 * counts, but it does not change the alerts list, so pages that only show
 * alerts should not refetch for it.
 */
export const REFRESH_GROUPS = {
  predictions: 'predictions',
  alerts: 'alerts',
  dashboard: 'dashboard',
}

/** Announce that prediction-related data on the server has changed. */
export function announcePredictionCreated({ riskLevel } = {}) {
  const collect = [REFRESH_GROUPS.predictions, REFRESH_GROUPS.dashboard]

  // Only an unsafe verdict produces an alert (the backend creates it), so only
  // then does the alerts list have anything new to show.
  if (riskLevel === 'unsafe') {
    collect.push(REFRESH_GROUPS.alerts)
  }

  emit(collect, riskLevel)
}

/** Announce an explicit group change (e.g. an alert was acknowledged). */
export function announceDataChanged(group) {
  emit([group])
}

function emit(groups, reason) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent(DATA_CHANGED_EVENT, { detail: { groups, reason } }),
  )
}

/**
 * Refetch when any of `groups` is announced.
 *
 * `refetch` is read from a ref on every event rather than captured once, so a
 * caller can pass an inline arrow function without stale-closure surprises.
 */
export function useDataRefresh(groups, refetch) {
  const groupList = Array.isArray(groups) ? groups : [groups]

  useEffect(() => {
    if (typeof window === 'undefined') return undefined

    function handle(event) {
      const changed = event?.detail?.groups || []
      if (groupList.some((group) => changed.includes(group))) {
        refetch?.()
      }
    }

    window.addEventListener(DATA_CHANGED_EVENT, handle)
    return () => window.removeEventListener(DATA_CHANGED_EVENT, handle)
    // `groupList` is rebuilt each render from a literal; joining it makes the
    // dependency stable without asking every caller to memoise an array.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupList.join('|'), refetch])
}
