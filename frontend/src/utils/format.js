import { RISK_LEVELS } from '@/utils/constants'

/** Format an ISO timestamp for display, tolerant of null.
 *
 * The backend stores naive UTC datetimes, so the value is parsed as UTC and
 * rendered in India Standard Time — the clock the user actually reads. An
 * explicit zone matters because a bare ISO string would otherwise be read as
 * local time on machines outside IST and drift by hours. `en-IN` keeps the
 * 12-hour railway-clock style; callers passing their own options still win.
 */
export function formatDate(value, options = {}) {
  if (!value) return '—'
  const date = parseServerTime(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Asia/Kolkata',
    hour12: true,
    ...options,
  }).format(date)
}

/**
 * Parse a timestamp from the Flask API.
 *
 * SQLAlchemy serialises a naive `datetime` ("2026-09-18T17:15:00") with no
 * timezone suffix. `new Date()` reads a bare datetime as *local* time, so a
 * UTC value renders hours off — a reply sent seconds ago can appear to have
 * arrived in the morning. Appending `Z` marks it as UTC explicitly.
 *
 * Falls back to the local clock when the value is missing or unparseable, so a
 * malformed timestamp never renders as "Invalid Date" or an empty label.
 */
export function parseServerTime(value) {
  if (!value) return new Date()
  if (value instanceof Date) return value
  const text = String(value)
  // Only add the zone when one is absent; a value that already ends in `Z` or
  // carries a +HH:MM offset must be left exactly as it is.
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text)
  const date = new Date(hasZone ? text : `${text}Z`)
  return Number.isNaN(date.getTime()) ? new Date() : date
}

/**
 * THE ONE PREDICTION TIMESTAMP, split so every surface can print it identically.
 *
 * A prediction is made once, at one instant, and its stored `created_at` is the
 * only timestamp that exists. History, the Reports sheet and the PDF/email must
 * all render that SAME stored value in the SAME clock and the SAME words — the
 * report the user downloads cannot disagree with the row they clicked.
 *
 * The wording here is the exact mirror of the backend's `app/utils/display_time`
 * (`format_ist` / `format_ist_time`): India Standard Time, 12-hour clock,
 * `18 Sep 2026` for the date and `6:45:30 pm` for the time. Keeping the two in
 * step is what makes the on-screen row and the generated PDF match minute for
 * minute.
 *
 * Returns `{ date, time, combined }`, all derived from the one parse, so a
 * caller can never assemble a date from one instant and a time from another.
 * A missing or unparseable stamp yields `—` for each part rather than a
 * fabricated clock reading.
 */
export function formatPredictionStamp(value) {
  const empty = { date: '—', time: '—', combined: '—' }
  if (!value) return empty
  const date = parseServerTime(value)
  if (Number.isNaN(date.getTime())) return empty
  const day = new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Kolkata',
  }).format(date)
  const time = new Intl.DateTimeFormat('en-IN', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    timeZone: 'Asia/Kolkata',
  })
    .format(date)
    .toLowerCase()
  return { date: day, time, combined: `${day}, ${time}` }
}

/** Format a clock time (e.g. "14:05") for chat timestamps, in IST. */
export function formatTime(value) {
  if (!value) return ''
  const date = value instanceof Date ? value : parseServerTime(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZone: 'Asia/Kolkata',
  }).format(date)
}

/** Format a confidence value (0–1) as a percentage string. */
export function formatPercent(value, fractionDigits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(fractionDigits)}%`
}

/** Format a numeric measurement, avoiding float noise like 7.000001. */
export function formatNumber(value, fractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: fractionDigits,
  })
}

/**
 * Describe the water source a stored reading carries, or say honestly that it is
 * not known.
 *
 * ONE RULE, SHARED BY EVERY SCREEN. The backend already stores the evidence
 * separately: `water_source_type` is a source mapped AT the sampled point,
 * `nearby_water_source` is the closest real feature found with its real
 * distance. So the wording is:
 *
 *   1. an identified source            → "Pond water"
 *   2. an identified source plus a real nearby feature → "Well water (nearest: X — 0.40 km)"
 *   3. a nearby feature but no source at the point   → "Nearby water sources: X — 0.40 km"
 *   4. nothing at all                              → "Water source information unavailable"
 *
 * It NEVER invents a type, a name, a distance or a measurement, and it never
 * substitutes a default such as "borewell" or "municipal" for missing evidence.
 * Every caller renders this text verbatim, so the same record can never be
 * described one way on History and another way in the report.
 */
export function waterSourceLabel(row, options = {}) {
  const type = row?.water_source_type ? String(row.water_source_type).trim() : ''
  const name = row?.nearby_water_source ? String(row.nearby_water_source).trim() : ''
  const rawDistance = row?.nearby_water_source_distance
  const distance =
    rawDistance === null || rawDistance === undefined || rawDistance === ''
      ? null
      : `${Number(rawDistance)} km`

  const nearby = [name, distance].filter(Boolean).join(' — ')

  if (type) {
    return nearby ? `${type} (nearest: ${nearby})` : type
  }
  if (name) return `Nearby water sources: ${nearby}`
  return options.empty ?? 'Water source information unavailable'
}

/** Tailwind classes for a risk level — used by badges and chart fills. */
export function riskTone(riskLevel) {
  switch (riskLevel) {
    case RISK_LEVELS.safe:
      return { badge: 'badge-safe', hex: 'var(--safe)', label: 'Safe' }
    case RISK_LEVELS.moderate:
      return { badge: 'badge-moderate', hex: 'var(--moderate)', label: 'Moderate' }
    case RISK_LEVELS.unsafe:
      return { badge: 'badge-unsafe', hex: 'var(--unsafe)', label: 'Unsafe' }
    default:
      return { badge: 'badge bg-slate-100 text-slate-600', hex: '#94a3b8', label: 'Unknown' }
  }
}

/** Turn a snake_case field name into a readable label. */
export function humanize(value) {
  if (!value) return ''
  return String(value)
    .replace(/_/g, String.fromCharCode(32))
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Build a query string, dropping empty values. */
export function buildQuery(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.append(key, value)
    }
  })
  const query = search.toString()
  return query ? `?${query}` : ''
}

/** Extract a human-readable message from an axios error. */
export function errorMessage(error, fallback = 'Something went wrong. Please try again.') {
  if (!error) return fallback
  return error.message || fallback
}
