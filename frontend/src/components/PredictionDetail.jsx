/**
 * Detail view for a single stored prediction.
 *
 * Fetches `GET /predictions/<id>` rather than rendering the row the table
 * already has: the endpoint enforces ownership server-side, so this is the only
 * way to be sure the full record shown belongs to the signed-in account. The
 * table row is used purely as the loading placeholder.
 */

import { useEffect, useState } from 'react'

import { predictionApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Icon from '@/components/Icon'
import PredictionExplanation from '@/components/PredictionExplanation'
import Spinner from '@/components/Spinner'
import { ICONS } from '@/config/navigation'
import { FEATURE_META, FEATURE_NAMES } from '@/utils/constants'
import { errorMessage, formatDate, formatNumber, formatPercent, waterSourceLabel } from '@/utils/format'

/**
 * STEP 33: one label/value line in the Location list.
 *
 * THE ICON IS THE LABEL'S MARK, NOT THE VALUE'S. It sits inside the `<dt>`, on
 * the left of the row, and `Icon` marks it `aria-hidden` — so a screen reader
 * hears "Place, Karaikudi" and never the pin. The value is plain text in the
 * `<dd>` and is always read in full, including a pincode: `tabular` goes on the
 * `<dd>` for the numeric rows so the digits line up down the column, which is
 * the whole reason it is a prop and not a hard-coded class.
 *
 * `capitalize` is likewise a prop: the water source type is stored lower-case by
 * the backend ("ground water") and is shown title-cased, while the place name is
 * already cased and must be left exactly as it was typed.
 *
 * `items-start` on the row, so a long place name wraps against the first line of
 * its label rather than being vertically centred against a one-line label.
 */
function LocationRow({ icon, label, children, tabular = false, capitalize = false }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="flex shrink-0 items-center gap-1.5 text-slate-500 dark:text-slate-400">
        <Icon path={ICONS[icon] || ICONS.info} className="h-4 w-4 shrink-0 text-slate-400 dark:text-slate-500" />
        {label}
      </dt>
      <dd
        className={`min-w-0 break-words text-right font-medium text-slate-800 dark:text-slate-100 ${
          capitalize ? 'capitalize' : ''
        } ${tabular ? 'tabular' : ''}`}
      >
        {children}
      </dd>
    </div>
  )
}

/** Read the five readings off a record, whichever shape came back. */
function readingsFrom(record) {
  if (!record) return null
  // The stored row exposes the parameters at the top level; the predict
  // response nests them under `parameters`. Support both so this panel works
  // whichever endpoint supplied the record.
  if (record.parameters) {
    return Object.fromEntries(
      FEATURE_NAMES.map((name) => [name, record.parameters[name]?.value]),
    )
  }
  return Object.fromEntries(FEATURE_NAMES.map((name) => [name, record[name]]))
}

export default function PredictionDetail({ predictionId, fallback, onClose }) {
  const [record, setRecord] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!predictionId) return undefined

    let active = true
    setLoading(true)
    setError(null)
    setRecord(null)

    predictionApi
      .getById(predictionId)
      .then((response) => {
        if (!active) return
        setRecord(response?.data || null)
        if (!response?.data) {
          setError('That prediction could not be found.')
        }
      })
      .catch((err) => {
        if (!active) return
        // A 404 here also covers trying to open another account's record, since
        // the backend deliberately does not distinguish the two.
        setError(
          err?.status === 404
            ? 'That prediction could not be found, or it does not belong to your account.'
            : errorMessage(err, 'Could not load this prediction.'),
        )
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [predictionId])

  const display = record || fallback
  const readings = readingsFrom(display)
  const risk = display?.prediction || display?.risk_level

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-900/40 backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label="Prediction detail"
      onClick={onClose}
    >
      {/* Stop clicks inside the panel from closing it. The panel is full-width on
          phones and capped on larger screens, so it never overflows the viewport. */}
      <div
        className="h-full w-full max-w-lg overflow-y-auto overscroll-contain bg-white p-5 shadow-panel sm:p-6 dark:bg-slate-900"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="mb-5 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-tight text-slate-900 dark:text-white">
              Prediction detail
            </h2>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
              {display?.created_at ? formatDate(display.created_at) : 'Loading…'}
            </p>
          </div>
          <Button variant="secondary" onClick={onClose} className="shrink-0 px-2.5 py-1.5 text-xs">
            Close
          </Button>
        </header>

        {loading ? (
          <Spinner label="Loading this prediction…" />
        ) : error ? (
          <div
            className="rounded-card border-unsafe-light bg-unsafe-light/40 px-3.5 py-3 text-sm text-unsafe-dark dark:border-unsafe dark:bg-unsafe/10 dark:text-unsafe-light"
            role="alert"
          >
            {error}
          </div>
        ) : (
          <div className="space-y-5">
            {/* --- Verdict + confidence --- */}
            <div className="flex items-center justify-between gap-4 rounded-card border-slate-100 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800">
              <div>
                <p className="text-2xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Prediction
                </p>
                <p className="mt-1 text-xl font-bold uppercase tracking-tight text-slate-900 dark:text-white">
                  {risk}
                </p>
              </div>
              <div className="text-right">
                <p className="text-2xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Prediction Confidence
                </p>
                <p className="mt-1 text-xl font-semibold text-slate-900 tabular dark:text-white">
                  {formatPercent(display?.confidence, 1)}
                </p>
                <p className="mt-1 text-2xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Risk: {{ safe: 'Low', moderate: 'Medium', unsafe: 'High' }[risk] || '—'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* COLOURED VERDICT: red unsafe, yellow moderate, green safe. */}
              <Badge risk={risk} button />
              <span className="text-xs text-slate-400">Record #{display?.id}</span>
              {display?.model_version && (
                <span className="text-xs text-slate-400">· {display.model_version}</span>
              )}
            </div>

            {/* --- Location / water source ------------------------------------
                Where this sample was taken, when the prediction carried a
                location. Shown as a place, not as raw coordinates.

                STEP 33: NO EMOJI, AND EVERY FIELD THE RECORD CARRIES.

                Two changes, and they pull in opposite directions.

                The "📍" and "💧" characters are gone from this list. They were
                OS-drawn glyphs — the browser chose the artwork, so they looked
                different on every machine, matched none of the surrounding type,
                and could not be styled. They are now `Icon` paths, which are part
                of the document, inherit `currentColor` and follow dark mode.

                And the list is now COMPLETE. It used to show only Place, Country,
                Pincode and Water Source, while the record also carries the area,
                the district and the state — so the panel was quietly dropping
                three of the fields the History page is supposed to display.

                AREA AND DISTRICT ARE RENDERED ONLY WHEN THE RECORD HAS THEM, and
                that is a data question rather than a styling one. `location_district`
                is NOT a stored column: the backend echoes it in the predict
                response and deliberately does not persist it, so a record read back
                from history will not have one. Rather than print "Not Available"
                for a field the database never held — which reads as a gap in the
                record when it is really a gap in the schema — each row renders
                only when its own field is present, and the panel stays a truthful
                picture of what was actually stored.

                NEARBY SOURCE IS SHOWN TOO. `nearby_water_source` and its distance
                are stored alongside the source type precisely so this identification
                survives a change in the mapped water data, and this was the one
                place it had never been surfaced. */}
            {(display?.location_name ||
              display?.location_city ||
              display?.location_area ||
              display?.water_source_type ||
              display?.nearby_water_source) && (
              <div>
                <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                  Location
                </p>
                <dl className="space-y-2 rounded-card border-slate-100 bg-slate-50 px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-800">
                  {(display?.location_name || display?.location_city) && (
                    <LocationRow icon="location" label="Place">
                      {[display.location_name || display.location_city]
                        .filter(Boolean)
                        .join(', ')}
                    </LocationRow>
                  )}
                  {display?.location_area && (
                    <LocationRow icon="info" label="Area">
                      {display.location_area}
                    </LocationRow>
                  )}
                  {display?.location_district && (
                    <LocationRow icon="info" label="District">
                      {display.location_district}
                    </LocationRow>
                  )}
                  {display?.location_state && (
                    <LocationRow icon="info" label="State">
                      {display.location_state}
                    </LocationRow>
                  )}
                  {display?.location_country && (
                    <LocationRow icon="info" label="Country">
                      {display.location_country}
                    </LocationRow>
                  )}
                  {display?.location_pincode && (
                    <LocationRow icon="info" label="Pincode" tabular>
                      {display.location_pincode}
                    </LocationRow>
                  )}
                  {/* PROMPT 4: `waterSourceLabel` gives the shared, honest wording —
                      the identified type, the nearest real nearby source with its
                      real distance, or "Water source information unavailable". It
                      replaces the two separate conditionals this used to have,
                      which left a record with only a nearby source showing nothing. */}
                  <LocationRow icon="droplet" label="Water Source">
                    {waterSourceLabel(display)}
                  </LocationRow>
                </dl>
              </div>
            )}

            {/* --- Every stored reading --- */}
            <div>
              <p className="mb-3 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                Recorded parameters
              </p>
              <dl className="divide-y divide-slate-100 border-y border-slate-100 text-sm dark:divide-slate-700 dark:border-slate-700">
                {FEATURE_NAMES.map((name) => (
                  <div key={name} className="flex items-center justify-between py-2.5">
                    <dt className="text-slate-500 dark:text-slate-400">
                      {FEATURE_META[name].label}
                      <span className="ml-1 text-xs text-slate-400">
                        {FEATURE_META[name].unit}
                      </span>
                    </dt>
                    <dd className="font-medium text-slate-800 tabular dark:text-slate-100">
                      {formatNumber(readings?.[name])}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>

            {/* --- Explanation, reusing the same component as the predict page --- */}
            <div>
              <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                What this means
              </p>
              <PredictionExplanation result={display} values={readings} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
