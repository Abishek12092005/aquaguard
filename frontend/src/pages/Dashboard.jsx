import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Link } from 'react-router-dom'
import { useTheme } from '@/context/useTheme'

import { dashboardApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Card from '@/components/Card'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import Icon from '@/components/Icon'
import PageHeader from '@/components/PageHeader'
import LocationPinIcon from '@/components/LocationPinIcon'
import Spinner from '@/components/Spinner'
import StatCard from '@/components/StatCard'
import { ICONS } from '@/config/navigation'
import { useApi } from '@/hooks/useApi'
import { ROUTES } from '@/utils/constants'
import { waterSourceLabel } from '@/utils/format'
import { REFRESH_GROUPS, useDataRefresh } from '@/utils/dataRefresh'
import { formatDate, formatNumber, formatPercent } from '@/utils/format'

const DISTRIBUTION_COLORS = {
  safe: '#16a34a',
  moderate: '#d97706',
  unsafe: '#dc2626',
}

const DISTRIBUTION_LABELS = {
  safe: 'Safe',
  moderate: 'Moderate',
  unsafe: 'Unsafe',
}

// --- Shared chart styling -------------------------------------------------
// Recharts takes styling as props, not classes, so the values live here and are
// spread into every chart. That is what keeps the three charts looking like one
// system rather than three separate ones: same axis weight, same grid, same
// tooltip surface, same font.
const AXIS_TICK = { fontSize: 12, fill: '#64748b' }
const GRID_STROKE = '#e2e8f0'

const TOOLTIP_PROPS = {
  cursor: { fill: 'rgba(148, 163, 184, 0.12)' },
  contentStyle: {
    borderRadius: '0.625rem',
    border: '1px solid #e2e8f0',
    boxShadow: '0 10px 24px -6px rgb(15 23 42 / 0.16)',
    fontSize: 12,
    padding: '8px 10px',
  },
  labelStyle: { color: '#0f172a', fontWeight: 600, marginBottom: 2 },
  itemStyle: { color: '#475569', padding: 0 },
}

// DARK MODE: the chart tooltip used to stay a white card on the dark page.
// These are the same shapes with dark surfaces and light text; the light theme
// keeps the original values above.
const DARK_AXIS_TICK = { fontSize: 12, fill: '#94a3b8' }
const DARK_GRID_STROKE = '#334155'
const DARK_TOOLTIP_PROPS = {
  cursor: { fill: 'rgba(148, 163, 184, 0.12)' },
  contentStyle: {
    borderRadius: '0.625rem',
    border: '1px solid #334155',
    background: '#0f172a',
    color: '#f1f5f9',
    boxShadow: '0 10px 24px -6px rgb(0 0 0 / 0.4)',
    fontSize: 12,
    padding: '8px 10px',
  },
  labelStyle: { color: '#f8fafc', fontWeight: 600, marginBottom: 2 },
  itemStyle: { color: '#cbd5e1', padding: 0 },
}

const LEGEND_PROPS = { iconSize: 8, wrapperStyle: { fontSize: 12, paddingTop: 8 } }

/** A card that renders loading / error / empty consistently. */
function Section({ loading, error, onRetry, empty, emptyTitle, emptyText, children }) {
  if (loading) return <Spinner label="Loading…" />
  if (error) return <ErrorState message={error} onRetry={onRetry} />
  if (empty) return <EmptyState title={emptyTitle} description={emptyText} />
  return children
}

export default function Dashboard() {
  const summary = useApi(() => dashboardApi.summary(), [])
  const recent = useApi(() => dashboardApi.recent(6), [])

  // A prediction submitted on the Predict page changes every figure here.
  // Refetching keeps this screen true without asking the user to reload.
  useDataRefresh(REFRESH_GROUPS.dashboard, () => {
    summary.refetch()
    recent.refetch()
  })

  const { isDark } = useTheme()
  const axisTick = isDark ? DARK_AXIS_TICK : AXIS_TICK
  const gridStroke = isDark ? DARK_GRID_STROKE : GRID_STROKE
  const tooltipProps = isDark ? DARK_TOOLTIP_PROPS : TOOLTIP_PROPS

  const totals = summary.data?.data?.totals
  const charts = summary.data?.data?.charts
  const latest = summary.data?.data?.latest_prediction
  const confidence = summary.data?.data?.average_confidence

  const distribution = (charts?.distribution || []).map((item) => ({
    ...item,
    label: DISTRIBUTION_LABELS[item.label] || item.label,
    color: DISTRIBUTION_COLORS[item.label],
  }))
  const distributionTotal = distribution.reduce((sum, item) => sum + item.value, 0)

  const trend = (charts?.trend || []).map((point) => ({
    ...point,
    date: point.date?.slice(5),
  }))

  const parameters = (charts?.parameters || []).filter((row) => row.mean != null)

  const predictions = recent.data?.data?.recent_predictions || []
  const alerts = recent.data?.data?.recent_alerts || []

  return (
    <div>
      {/* The greeting used to live here as the Dashboard title. It now belongs
          on the HOME screen, which is where a signed-in user lands first and
          where "welcome back" reads naturally. The Dashboard is a data screen,
          so its heading states what it is. `breadcrumbClassName` makes the
          "Overview" overline WHITE, as required. */}
      <PageHeader
        breadcrumb="Overview"
        breadcrumbClassName="text-white dark:text-white"
        title="Dashboard"
        description="Monitor your water quality readings and safety status."
        actions={
          // POSITIONING IS LEFT TO PageHeader, which right-aligns the action
          // block against the heading — so this is a plain inline-flex wrapper.
          <Link to={ROUTES.predict} className="inline-flex">
            <Button
              // Compact on a phone so it shares the row with the heading; full
              // size from `sm` up.
              // DARK MODE IS A WHITE BUTTON WITH BLACK TEXT.
              //
              // The brand primary is a blue control with white text. On the dark
              // slate page that made the button a blue block on a blue-black
              // background — present, but not the brightest thing on screen. This
              // inverts it in dark mode only: a white surface with black text,
              // the highest-contrast treatment on a dark page.
              //
              // HOVER IS BLACK WITH WHITE TEXT, matching every other button in
              // dark mode and the .btn-* rules in index.css.
              className="px-2.5 py-1.5 text-xs sm:px-3.5 sm:py-2 sm:text-sm dark:bg-white dark:text-black dark:ring-1 dark:ring-white/20 dark:hover:bg-black dark:hover:text-white dark:active:bg-black dark:active:text-white"
            >
              <Icon path={ICONS.predict} className="h-4 w-4 shrink-0" />
              New prediction
            </Button>
          </Link>
        }
      />

      {/* --- KPI row --- */}
      <section aria-labelledby="kpis-heading" className="mb-6">
        <h3 id="kpis-heading" className="sr-only">
          Summary statistics
        </h3>
        {/* TWO CARDS PER ROW ON A PHONE.

            `grid-cols-2` from the start (not `sm:grid-cols-2`) puts the first
            four KPI cards two-up at 390px, so the whole summary is visible
            without scrolling. `gap-3` on mobile keeps the pair from crowding;
            `sm:gap-4`/`xl:grid-cols-4` restore the roomier desktop layout. */}
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <StatCard
            label="Total predictions"
            value={formatNumber(totals?.total ?? 0, 0)}
            hint="All readings recorded"
            loading={summary.loading}
            error={summary.error}
            onRetry={summary.refetch}
            icon={<Icon path={ICONS.history} className="h-5 w-5" />}
            className="animate-zoom-in xl:animate-slide-in-left"
            style={{ animationDelay: '0s' }}
          />
          <StatCard
            label="Safe predictions"
            value={formatNumber(totals?.safe ?? 0, 0)}
            tone="safe"
            hint={confidence != null ? `${formatPercent(confidence)} avg confidence` : 'Potable verdicts'}
            loading={summary.loading}
            error={summary.error}
            onRetry={summary.refetch}
            icon={<Icon path={ICONS.predict} className="h-5 w-5" />}
            className="animate-zoom-in xl:animate-slide-in-left"
            style={{ animationDelay: '0.08s' }}
          />
          <StatCard
            label="Moderate predictions"
            value={formatNumber(totals?.moderate ?? 0, 0)}
            tone="moderate"
            hint="Borderline results"
            loading={summary.loading}
            error={summary.error}
            onRetry={summary.refetch}
            icon={<Icon path={ICONS.analytics} className="h-5 w-5" />}
            className="animate-zoom-in xl:animate-slide-in-right"
            style={{ animationDelay: '0.16s' }}
          />
          <StatCard
            label="Unsafe predictions"
            value={formatNumber(totals?.unsafe ?? 0, 0)}
            tone="unsafe"
            hint="Flagged for attention"
            loading={summary.loading}
            error={summary.error}
            onRetry={summary.refetch}
            icon={<Icon path={ICONS.alerts} className="h-5 w-5" />}
            className="animate-zoom-in xl:animate-slide-in-right"
            style={{ animationDelay: '0.24s' }}
          />
        </div>
      </section>

      {/* --- Latest prediction --- */}
      <Card
        title="Latest prediction"
        subtitle="Your most recent water sample"
        className="mb-6 animate-zoom-in"
        actions={
          <Link to={ROUTES.history} className="text-sm font-medium text-aqua-700 hover:underline dark:text-aqua-300">
            View all
          </Link>
        }
      >
        <Section
          loading={summary.loading}
          error={summary.error}
          onRetry={summary.refetch}
          empty={!latest}
          emptyTitle="No predictions yet"
          emptyText="Submit your first water sample to see the verdict and confidence score here."
        >
          {latest && (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              {/* The latest reading's verdict: red unsafe, yellow moderate, green safe. */}
              <Badge risk={latest.risk_level} button />
              <span className="text-sm text-slate-600 tabular">
                {formatPercent(latest.confidence)} confidence
              </span>
              {/* The place, with the exact stored pincode or an explicit
                  "Not Available" - never a guessed one. */}
              {(latest.location_name || latest.location_city || latest.location_pincode) && (
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  <LocationPinIcon className="mr-1 inline-block h-3.5 w-3.5 align-[-0.1em] text-aqua-600 dark:text-aqua-300" animated={false} />
                  {[latest.location_name || latest.location_city, latest.location_state]
                    .filter(Boolean)
                    .join(', ')}
                  {latest.location_name || latest.location_city ? ' — ' : ''}
                  {/* PROMPT 4: actual stored source type when present; otherwise
                      the pincode, else an explicit "unavailable" — no guesses. */}
                  {latest.water_source_type
                    ? ` — Water source: ${latest.water_source_type}`
                    : latest.location_pincode
                      ? `Pincode: ${latest.location_pincode}`
                      : ' — Water source information unavailable'}
                </span>
              )}
              <span className="text-xs text-slate-400">{formatDate(latest.created_at)}</span>
            </div>
          )}
        </Section>
      </Card>

      {/* --- Charts --- */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card
          className="animate-slide-in-left"
          title="Prediction distribution"
          subtitle="Safe vs moderate vs unsafe"
        >
          <Section
            loading={summary.loading}
            error={summary.error}
            onRetry={summary.refetch}
            empty={distributionTotal === 0}
            emptyTitle="No data yet"
            emptyText="The distribution appears once you have recorded some readings."
          >
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={distribution}
                    dataKey="value"
                    nameKey="label"
                    innerRadius={54}
                    outerRadius={88}
                    paddingAngle={2}
                    // White in light mode; the dark card's surface in dark, so
                    // the pie's segment gaps match the card behind it.
                    stroke={isDark ? '#1e293b' : '#fff'}
                    strokeWidth={2}
                  >
                    {distribution.map((entry) => (
                      <Cell key={entry.label} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip {...tooltipProps} />
                  <Legend {...LEGEND_PROPS} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </Section>
        </Card>

        <Card
          className="animate-slide-in-right"
          title="Recent prediction trend"
          subtitle="Volume and unsafe results"
        >
          <Section
            loading={summary.loading}
            error={summary.error}
            onRetry={summary.refetch}
            empty={trend.length === 0}
            emptyTitle="No trend to show"
            emptyText="The chart appears after a few predictions have been recorded."
          >
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trend} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={axisTick}
                    tickLine={false}
                    axisLine={{ stroke: gridStroke }}
                  />
                  <YAxis
                    allowDecimals={false}
                    tick={axisTick}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip {...tooltipProps} />
                  <Legend {...LEGEND_PROPS} />
                  <Line
                    type="monotone"
                    dataKey="predictions"
                    name="Predictions"
                    stroke="#0e9de8"
                    strokeWidth={2}
                  />
                  <Line
                    type="monotone"
                    dataKey="unsafe"
                    name="Unsafe"
                    stroke="#dc2626"
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Section>
        </Card>
      </div>

      {/* --- Parameter visualization --- */}
      <div className="mt-6">
        <Card
          className="animate-slide-in-left"
          title="Water parameter visualization"
          subtitle="Mean reading per parameter"
        >
          <Section
            loading={summary.loading}
            error={summary.error}
            onRetry={summary.refetch}
            empty={parameters.length === 0}
            emptyTitle="No parameter data"
            emptyText="Average readings appear once predictions have been recorded."
          >
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={parameters} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={axisTick}
                    tickLine={false}
                    axisLine={{ stroke: gridStroke }}
                  />
                  <YAxis tick={axisTick} tickLine={false} axisLine={false} />
                  <Tooltip {...tooltipProps} />
                  <Bar dataKey="mean" name="Mean" fill="#0e9de8" radius={[5, 5, 0, 0]} maxBarSize={72} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Section>
        </Card>
      </div>

      {/* --- Recent activity + alerts --- */}
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card
          className="animate-slide-in-left"
          title="Recent activity"
          subtitle="Your latest predictions"
          actions={
            <Link to={ROUTES.history} className="text-sm font-medium text-aqua-700 hover:underline dark:text-aqua-300">
              View all
            </Link>
          }
        >
          <Section
            loading={recent.loading}
            error={recent.error}
            onRetry={recent.refetch}
            empty={predictions.length === 0}
            emptyTitle="No activity yet"
            emptyText="Your submitted samples will appear here."
          >
            <ul className="divide-y divide-slate-100">
              {predictions.map((row) => (
                <li
                  key={row.id}
                  // NO HOVER ON THESE ROWS. This list is a read-only summary, not a
                  // menu: the row is not clickable and leads nowhere, so lighting
                  // it up under the pointer promised an interaction that does not
                  // exist. The only way into the full list is "View all", which is
                  // the control that actually navigates.
                  className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    {/* Coloured verdict: red unsafe, yellow moderate, green safe. */}
                    <Badge risk={row.prediction} button />
                    <span className="min-w-0">
                      {/* The place the sample was taken, with the stored pincode
                          when the row carries one - "Pincode: Not Available"
                          when it does not. Never inferred from the place name. */}
                      {(row.location_name || row.location_city) && (
                        <span className="block truncate text-xs font-medium text-slate-600 dark:text-slate-300">
                          {/* PROFESSIONAL SVG PIN — NEVER AN EMOJI.

                              This was the OS-drawn "📍", which rendered as a
                              different flat pushpin on every platform and could
                              not inherit the aqua palette or dark mode.

                              `animated` adds only the NON-SPATIAL accent (a
                              pulse at the pin's foot); the pin body itself does
                              not translate at any setting, so the marker holds
                              its position and the row never shifts. */}
                          <LocationPinIcon
                            className="mr-1 inline-block h-3.5 w-3.5 shrink-0 align-[-0.1em] text-aqua-600 dark:text-aqua-300"
                            animated
                          />
                          {row.location_name || row.location_city}
                        </span>
                      )}
                      <span className="block truncate text-xs text-slate-400">
                        {/* PROMPT 4: the actual stored water source, shown only
                            when the record carries one — never guessed. */}
                        {waterSourceLabel(row, {
                          empty: row.location_pincode
                            ? `Pincode: ${row.location_pincode}`
                            : 'Water source information unavailable',
                        })}
                      </span>
                      <span className="block truncate text-xs text-slate-400">
                        {formatDate(row.created_at)}
                      </span>
                    </span>
                  </div>
                  <span className="shrink-0 text-sm font-medium text-slate-600 tabular dark:text-slate-200">
                    {formatPercent(row.confidence)}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        </Card>

        <Card
          className="animate-slide-in-right"
          title="Recent alerts"
          subtitle="Unsafe water notifications"
          actions={
            <Link to={ROUTES.alerts} className="text-sm font-medium text-aqua-700 hover:underline dark:text-aqua-300">
              View all
            </Link>
          }
        >
          <Section
            loading={recent.loading}
            error={recent.error}
            onRetry={recent.refetch}
            empty={alerts.length === 0}
            emptyTitle="No alerts"
            emptyText="Unsafe detections will be listed here."
          >
            <ul className="divide-y divide-slate-100">
              {alerts.map((alert) => (
                <li
                  key={alert.id}
                  // Same reasoning as the activity list above: these rows are not
                  // links, so they must not highlight as if they were. Opening the
                  // alerts screen is what "View all" is for.
                  className="flex items-start gap-3 py-3 first:pt-0 last:pb-0"
                >
                  <Badge tone={alert.is_read ? 'slate' : 'unsafe'}>
                    {alert.is_read ? 'Acknowledged' : 'Active'}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-slate-700 dark:text-slate-100">
                      {alert.message}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-400">
                      {formatDate(alert.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        </Card>
      </div>
    </div>
  )
}
