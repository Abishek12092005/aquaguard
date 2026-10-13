import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { predictionApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Card from '@/components/Card'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import Icon from '@/components/Icon'
import PageHeader from '@/components/PageHeader'
import PredictionDetail from '@/components/PredictionDetail'
import Spinner from '@/components/Spinner'
import { ICONS } from '@/config/navigation'
import { useApi } from '@/hooks/useApi'
import { FEATURE_META, FEATURE_NAMES, ROUTES } from '@/utils/constants'
import { REFRESH_GROUPS, useDataRefresh } from '@/utils/dataRefresh'
import {
  formatNumber,
  formatPercent,
  formatPredictionStamp,
  waterSourceLabel,
} from '@/utils/format'
import { predictionId } from '@/utils/reports'

/** The plain-word risk each verdict maps to: safe -> Low, moderate -> Medium,
 *  unsafe -> High. A reading of the model's own verdict, never a second score. */
const RISK_WORDS = {
  safe: 'Low',
  moderate: 'Medium',
  unsafe: 'High',
}

const FILTERS = [
  { key: undefined, label: 'All' },
  { key: 'safe', label: 'Safe' },
  { key: 'moderate', label: 'Moderate' },
  { key: 'unsafe', label: 'Unsafe' },
]

const SORTS = [
  { key: 'newest', label: 'Newest first' },
  { key: 'oldest', label: 'Oldest first' },
  { key: 'confidence', label: 'Most confident' },
]

const PER_PAGE = 20
/** Location, date, verdict, confidence and every recorded reading. */
const COLUMNS = [
  'Prediction ID',
  'Location',
  'Area',
  'City/Town',
  'District',
  'State',
  'Country',
  'Pincode',
  'Water Source',
  'Date',
  'Time',
  'Prediction',
  'Confidence',
  'Risk',
  ...FEATURE_NAMES.map((name) => FEATURE_META[name].label),
]

/**
 * STEP 33: the place a prediction was taken, as one readable line.
 *
 * Prefers the stored place name and falls back to the city, so a record submitted
 * from coordinates rather than a name still reads as a place. Returns null when the
 * sample has no location at all, so the cell can say so honestly rather than
 * showing a blank.
 *
 * THE STATE AND COUNTRY ARE NOT APPENDED HERE ANY MORE. They were joined onto this
 * one line before Step 33, which read as "Karaikudi, Tamil Nadu" with the country
 * dropped whenever the state existed — so a record stored with only a country, or
 * with neither, lost it silently. They now have their own line in the cell, next
 * to the area and district, and each is shown only if it is actually stored.
 */
function locationLine(row) {
  return row.location_name || row.location_city || null
}

/** True when the record has any administrative part worth a second line. */
function hasRegion(row) {
  return Boolean([
    row.location_area,
    row.location_district,
    row.location_state,
    row.location_country,
  ].filter(Boolean).length)
}

export default function History() {
  const [riskFilter, setRiskFilter] = useState(undefined)
  const [sort, setSort] = useState('newest')
  const [page, setPage] = useState(1)

  // The input updates immediately; the request follows once typing pauses, so
  // a search does not fire a request per keystroke.
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [openId, setOpenId] = useState(null)

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 350)
    return () => clearTimeout(timer)
  }, [searchInput])

  // Any change to the query resets to page 1. Without this, filtering while on
  // page 5 asks for a page that may no longer exist, and the empty table reads
  // as "no results" rather than "you are past the end".
  useEffect(() => {
    setPage(1)
  }, [riskFilter, sort, search])

  // Every filter is sent to the server so it applies to the whole history, not
  // just the twenty rows on screen.
  const { data, loading, error, refetch } = useApi(
    () =>
      predictionApi.history({
        page,
        per_page: PER_PAGE,
        risk_level: riskFilter,
        search: search || undefined,
        sort,
      }),
    [page, riskFilter, sort, search],
  )

  // A new prediction belongs in this list immediately.
  useDataRefresh(REFRESH_GROUPS.predictions, refetch)

  const rows = data?.data || []
  const meta = data?.meta || {}
  const filtersActive = Boolean(riskFilter || search)

  function clearFilters() {
    setRiskFilter(undefined)
    setSearchInput('')
    setSearch('')
    setSort('newest')
  }

  return (
    <div>
      <PageHeader
        breadcrumb="Records"
        title="Prediction History"
        description="Every water sample submitted here, newest first. There is no sign-in, so these are the shared records of this application rather than one person's private history."
        // ONE LINE: keeps the header a single line tall above the table.
        oneLine
      />

      <Card padded={false}>
        {/* --- Controls --- */}
        {/* `flex` was missing on this row, so `lg:flex-row` never applied and the
            filter chips sat above the search box on every screen size. */}
        <div className="flex flex-col gap-4 border-b border-slate-100 px-5 py-4 lg:flex-row lg:items-center lg:justify-between dark:border-slate-700">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Filter
            </span>
            {FILTERS.map((filter) => (
              <button
                key={filter.label}
                type="button"
                onClick={() => setRiskFilter(filter.key)}
                aria-pressed={riskFilter === filter.key}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  riskFilter === filter.key
                    ? 'bg-aqua-600 text-white shadow-sm dark:bg-aqua-700'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-black dark:hover:text-white'
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="sr-only" htmlFor="history-search">
              Search the recorded predictions
            </label>
            <div className="relative w-full sm:w-64">
              <Icon
                path={ICONS.search}
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
              />
              <input
                id="history-search"
                type="search"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search a reading or verdict…"
                className="input pl-9"
              />
            </div>
            <label className="sr-only" htmlFor="history-sort">
              Sort order
            </label>
            <select
              id="history-sort"
              value={sort}
              onChange={(event) => setSort(event.target.value)}
              className="input w-full sm:w-44"
            >
              {SORTS.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {loading ? (
          <Spinner label="Loading the prediction history…" />
        ) : error ? (
          <div className="p-5">
            <ErrorState message={error} onRetry={refetch} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Icon path={ICONS.history} className="h-6 w-6" />}
            title={filtersActive ? 'No matching predictions' : 'No predictions recorded'}
            description={
              filtersActive
                ? 'No record matches the current filter and search. Try a different reading, or clear the filters to see everything.'
                : 'Once you submit water samples, each one appears here with its verdict, readings and confidence score.'
            }
            action={
              filtersActive ? (
                <Button variant="secondary" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : (
                <Link to={ROUTES.predict} className="btn-primary inline-flex">
                  Analyze a water sample
                </Link>
              )
            }
          />
        ) : (
          <>
            {/* The wrapper owns the horizontal scroll, so the wide table scrolls
                inside the card instead of pushing the page sideways.

                The `min-w-[44rem]` this used to carry is gone: it overrode the
                shared `.table` floor with 704px, which is wider than the content
                column on a laptop once the sidebar is accounted for — so the
                table *always* overflowed and scrolled, even at 1280px. The
                shared 34rem floor plus tighter cell padding lets it fit. */}
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    {COLUMNS.map((label) => (
                      <th key={label} scope="col" className="text-center">
                        {label}
                      </th>
                    ))}
                    <th scope="col" className="text-center">
                      Detail
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.id}
                      className="cursor-pointer"
                      onClick={() => setOpenId(row.id)}
                    >
                      <td className="whitespace-nowrap text-center font-mono text-xs text-slate-600 dark:text-slate-300" onClick={(event) => event.stopPropagation()}>
                        {predictionId(row)}
                      </td>
                      <td className="whitespace-nowrap" onClick={(event) => event.stopPropagation()}>
                        {locationLine(row) || row.location_pincode || hasRegion(row) ? (
                          <span className="block">
                            <span className="flex items-center gap-1.5 text-slate-700 dark:text-slate-200">
                              <Icon path={ICONS.location} className="h-4 w-4 shrink-0 text-aqua-600 dark:text-aqua-300" />
                              <span className="block">{locationLine(row)}</span>
                            </span>
                            {/* PROMPT 4: the stored source — its type when one was
                                identified AT the point, the real nearest source with
                                its real distance when only nearby ones exist, and an
                                explicit "unavailable" otherwise. Never a guess. */}
                            <span className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-400">
                              <Icon path={ICONS.droplet} className="h-3.5 w-3.5 shrink-0" />
                              <span className="capitalize">{waterSourceLabel(row)}</span>
                            </span>
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">No location</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap text-center text-slate-600 dark:text-slate-300">{row.location_area || '—'}</td>
                      <td className="whitespace-nowrap text-center text-slate-600 dark:text-slate-300">{row.location_city || '—'}</td>
                      <td className="whitespace-nowrap text-center text-slate-600 dark:text-slate-300">{row.location_district || '—'}</td>
                      <td className="whitespace-nowrap text-center text-slate-600 dark:text-slate-300">{row.location_state || '—'}</td>
                      <td className="whitespace-nowrap text-center text-slate-600 dark:text-slate-300">{row.location_country || '—'}</td>
                      <td className="whitespace-nowrap text-center text-slate-600 dark:text-slate-300">{row.location_pincode || '—'}</td>
                      <td className="whitespace-nowrap text-center text-slate-600 dark:text-slate-300">{row.water_source_type || '—'}</td>
                      {/* THE STORED TIMESTAMP, SHOWN TWICE FROM ONE PARSE.

                          Date and Time are two slices of the row's own
                          `created_at` — the instant written to the database when
                          the prediction was created. Nothing is regenerated here.
                          `formatPredictionStamp` mirrors the backend's PDF/email
                          wording (IST, 12-hour clock), so the History row and the
                          downloaded report read the same minute. */}
                      <td className="whitespace-nowrap text-center text-slate-500 dark:text-slate-400">
                        {formatPredictionStamp(row.created_at).date}
                      </td>
                      <td className="whitespace-nowrap text-center text-slate-500 dark:text-slate-400">
                        {formatPredictionStamp(row.created_at).time}
                      </td>
                      <td>
                        {/* COLOURED VERDICT: red unsafe, yellow moderate, green safe. */}
                        <Badge risk={row.prediction || row.risk_level} button />
                      </td>
                      <td className="tabular text-center font-medium text-slate-700 dark:text-slate-200">
                        {formatPercent(row.confidence)}
                      </td>
                      <td className="whitespace-nowrap text-center text-slate-600 dark:text-slate-300">
                        {RISK_WORDS[row.prediction || row.risk_level] || '—'}
                      </td>
                      {FEATURE_NAMES.map((name) => (
                        <td key={name} className="tabular text-center text-slate-600 dark:text-slate-300">
                          {formatNumber(row[name])}
                        </td>
                      ))}
                      <td className="text-center">
                        <button
                          type="button"
                          onClick={(event) => {
                            // The row opens the panel too; stopping propagation
                            // keeps this click from firing the row handler as
                            // well and double-toggling the panel.
                            event.stopPropagation()
                            setOpenId(row.id)
                          }}
                          className="rounded-md px-2 py-1 text-xs font-semibold text-aqua-700 transition-colors hover:bg-aqua-50 dark:text-aqua-300 dark:hover:bg-aqua-900/50"
                          aria-label={`View details for prediction ${row.id}`}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* --- Pagination --- */}
            <div className="flex flex-col gap-3 border-t border-slate-100 px-5 py-4 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between dark:border-slate-700 dark:text-slate-400">
              <span className="tabular">
                Showing {(meta.page - 1) * meta.per_page + 1}–
                {Math.min(meta.page * meta.per_page, meta.total)} of {meta.total}
              </span>
              {/* PAGINATION IS READABLE IN DARK MODE.

                  These are `btn-secondary`, which in dark mode is a WHITE button
                  with BLACK text — so the label is dark on a light pill and
                  cannot disappear. The `dark:text-black` is stated explicitly
                  as well: the page's card-level colour remap in index.css exists
                  to lift muted text on a DARK surface, and on this LIGHT button
                  that same remap would turn the label light-on-light. Pinning it
                  here makes the intent local and independent of that global rule.

                  A real gap (`gap-3`) separates the two buttons from the page
                  counter between them, so the control is not one run-together
                  block. */}
              <div className="flex items-center gap-2 sm:gap-3">
                <button
                  type="button"
                  disabled={!meta.has_prev}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="btn-secondary px-2.5 py-1.5 text-xs dark:bg-white dark:text-black dark:hover:bg-black dark:hover:text-white"
                >
                  Previous
                </button>
                <span className="px-1 text-xs font-medium tabular text-slate-600 dark:text-slate-300">
                  Page {meta.page} of {meta.pages || 1}
                </span>
                <button
                  type="button"
                  disabled={!meta.has_next}
                  onClick={() => setPage((p) => p + 1)}
                  className="btn-secondary px-2.5 py-1.5 text-xs dark:bg-white dark:text-black dark:hover:bg-black dark:hover:text-white"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </Card>

      {openId && (
        <PredictionDetail
          predictionId={openId}
          fallback={rows.find((row) => row.id === openId)}
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  )
}
