import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { predictionApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Card from '@/components/Card'
import Icon from '@/components/Icon'
import PageHeader from '@/components/PageHeader'
import PredictionExplanation from '@/components/PredictionExplanation'
import { ICONS } from '@/config/navigation'
import { AI_CONTEXT } from '@/context/aquaAIContextObject'
import { useAquaAIContext } from '@/context/useAquaAIContext'
import { FEATURE_META, FEATURE_NAMES, RISK_LEVELS, ROUTES } from '@/utils/constants'
import { announcePredictionCreated } from '@/utils/dataRefresh'
import { errorMessage, formatDate, formatNumber, formatPercent, waterSourceLabel } from '@/utils/format'

/**
 * The plain-word risk that each verdict maps to: safe -> Low, moderate -> Medium,
 * unsafe -> High. This is a READING of the model's own verdict, not a separate
 * score - it is derived from the real output and cannot disagree with it.
 */
const RISK_WORDS = {
  safe: 'Low',
  moderate: 'Medium',
  unsafe: 'High',
}

/**
 * Manual Prediction — the live sample form.
 *
 * ONE JOB: enter the five water-quality readings and get a verdict back. There is
 * no location SECTION here - the "Location Information" block was removed in
 * STEP 4. STEP 15 adds a hand-off, not a section: "Enter Water Prediction" on
 * the Location page arrives here with the five readings already in the form and
 * the location travelling internally so the sample is stored against the right
 * place. Every value stays editable and the model still runs only when the
 * visitor presses "Analyze Water Quality".
 *
 * Submits the five parameters to `POST /predictions/predict`, which validates
 * them, runs the trained Random Forest, stores the row and returns the verdict
 * with a confidence score. Every value rendered here comes from that response.
 *
 * Failures are split by cause, because each needs different words and a
 * different recovery:
 *
 *   validation (422)   the backend rejected specific fields -> shown per field
 *   backend (4xx/5xx)  the request was fine, the server was not -> banner
 *   network            the request never arrived -> banner, stated as such
 *   loading            the submit button and the panel both report the wait
 */

const EMPTY_VALUES = Object.fromEntries(FEATURE_NAMES.map((name) => [name, '']))

/** Which fields are blank, so submit can explain itself before calling out. */
function findBlankFields(values) {
  return FEATURE_NAMES.filter((name) => String(values[name]).trim() === '')
}

/**
 * Per-field messages for everything the backend would reject.
 *
 * A field that is blank gets "required"; a field that holds something that is
 * not a number, or is outside the model's supported range, gets a message that
 * names the actual range. The bounds come from FEATURE_META - the same numbers
 * the inputs carry as min/max and the same numbers backend/app/constants.py
 * validates against - so this form cannot disagree with the API about what a
 * valid reading is.
 *
 * This runs on submit, not on every keystroke: flagging a half-typed number as
 * out of range while the visitor is still typing it would be noise, not help.
 */
function validateFields(values) {
  const errors = {}
  for (const name of FEATURE_NAMES) {
    const { label, min, max } = FEATURE_META[name]
    const raw = String(values[name]).trim()
    if (raw === '') {
      errors[name] = `${label} is required`
      continue
    }
    // Number('') is 0, which would let an empty box pass - already handled above.
    const value = Number(raw)
    if (!Number.isFinite(value)) {
      errors[name] = `${label} must be a number`
      continue
    }
    if (value < min || value > max) {
      errors[name] = `${label} must be between ${min} and ${max}`
    }
  }
  return errors
}

/**
 * How a field's current value was obtained, for the inline source label.
 *
 * REMOVED ALONG WITH THE LABEL IT FED. This used to print "User input required"
 * under every empty box and "Estimated" under a pre-filled one, which made an
 * ordinary blank input look like a warning about something being wrong with it.
 * Nothing is missing: the field is empty because the visitor has not typed it
 * yet, which the field's own label and the form's validation already say
 * plainly - in an error colour, on the field that is actually wrong, and only
 * once it is wrong.
 */

export default function Predict() {
  // STEP 15: the hand-off from Location Prediction.
  //
  // "Enter Water Prediction" on the Location page navigates here carrying the
  // selected location's five water-quality readings and its location metadata.
  // They SEED THE FORM ONCE, on arrival, and nothing more:
  //
  //   - every box stays an ordinary editable input, so any value can be corrected
  //     or retyped before analysing;
  //   - NO prediction is run automatically. The verdict still comes only from the
  //     visitor pressing "Analyze Water Quality";
  //   - the location travels with the sample when they do, so the stored row
  //     belongs to the place it was taken for. It is passed INTERNALLY ONLY and
  //     is never rendered: the "Location Information" section was removed in
  //     STEP 4 and this step does not bring it back.
  const navigation = useLocation()
  const handoff = navigation.state?.fromLocation ? navigation.state : null

  const [values, setValues] = useState(() => {
    if (!handoff?.readings) return EMPTY_VALUES
    // Only numbers the hand-off actually carries. A missing reading stays blank
    // rather than becoming a zero, so the "required" check still asks for it.
    return Object.fromEntries(
      FEATURE_NAMES.map((name) => {
        const value = handoff.readings[name]
        return [name, value === null || value === undefined || value === '' ? '' : String(value)]
      }),
    )
  })
  // The location that came with the form. Held so it can travel with the sample;
  // it is internal state, never part of the rendered page.
  const [carriedLocation] = useState(() => handoff?.location ?? null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const { announce, clear } = useAquaAIContext()

  // Identifies the newest in-flight request.
  //
  // `submitting` stops a double-click from sending two POSTs, but it does not
  // stop a slow FIRST response from landing after a second submission was
  // already sent - in which case the older verdict would overwrite the newer
  // one on screen. Every request stamps itself, and a response whose stamp is
  // not the latest is discarded, so what is displayed is always the answer to
  // the readings currently in the form.
  const requestId = useRef(0)

  // When the current request started, so the wait can be reported honestly
  // rather than left to an indefinite spinner.
  const [elapsedMs, setElapsedMs] = useState(0)

  // Tell the assistant panel whether a verdict is on screen, so it offers
  // "explain this result" only when there is a result to explain. This publishes
  // a screen state, not any data: the explanation itself comes from the
  // assistant's own tool call, never from here.
  useEffect(() => {
    if (result) announce(AI_CONTEXT.predictionResult)
    else clear()
    return clear
  }, [result, announce, clear])

  // The exact readings that were submitted, held separately from the form so
  // editing the inputs afterwards cannot silently rewrite the recorded sample.
  const [submitted, setSubmitted] = useState(null)

  function handleChange(event) {
    const { name, value } = event.target
    setValues((previous) => ({ ...previous, [name]: value }))
    // Clear this field's error as soon as the user starts fixing it.
    setFieldErrors((previous) => {
      if (!previous[name]) return previous
      const next = { ...previous }
      delete next[name]
      return next
    })
  }

  function handleReset() {
    setValues(EMPTY_VALUES)
    setFieldErrors({})
    setResult(null)
    setSubmitted(null)
    setError(null)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (submitting) return
    // --- Completeness and range check ---------------------------------
    // Only to save a round trip and to explain the problem in context. Every
    // field is checked against the model's supported range, so an impossible
    // reading is caught here instead of coming back as a 422. The backend still
    // validates everything; this never replaces that.
    const problems = validateFields(values)
    const invalidCount = Object.keys(problems).length
    if (invalidCount > 0) {
      setFieldErrors(problems)
      const missingCount = blanks.length
      setError({
        kind: 'validation',
        message:
          missingCount > 0
            ? `${missingCount} parameter${missingCount > 1 ? 's are' : ' is'} missing. Fill in every reading from your test before analysing.`
            : 'One or more readings are outside the range the model supports. Correct the highlighted field and analyse again.',
      })
      return
    }

    // Claim this request's slot. Any response that arrives for an EARLIER id
    // belongs to a superseded submission and is dropped.
    const id = ++requestId.current

    setSubmitting(true)
    setError(null)
    setFieldErrors({})
    // Drop the previous verdict the moment a new sample is submitted. The
    // panel shows a spinner instead, so an old verdict is never left on screen
    // where it reads as the answer to the readings just submitted.
    setResult(null)
    setElapsedMs(0)

    // Send numbers, not strings: the API contract is numeric, so the backend
    // does not have to interpret text. STEP 15: the location carried in from the
    // Location page rides along with the readings so the stored prediction is
    // attributed to the place it was taken for. When this screen is reached
    // directly there is no location and nothing extra is sent.
    const payload = {
      ...Object.fromEntries(FEATURE_NAMES.map((name) => [name, Number(values[name])])),
      ...(carriedLocation ? { ...carriedLocation } : {}),
    }

    const startedAt = performance.now()

    try {
      const response = await predictionApi.predict(payload)
      // Superseded by a newer submission - its answer is no longer wanted.
      if (id !== requestId.current) return

      const data = response?.data
      if (!data?.prediction) {
        // A 2xx carrying no verdict is a malformed response, not a result.
        // Saying so is better than rendering an empty verdict panel.
        setError({
          kind: 'backend',
          message: 'The server accepted the sample but returned no verdict. Please try again.',
        })
        return
      }

      setResult(data)
      setSubmitted(Object.fromEntries(FEATURE_NAMES.map((name) => [name, Number(values[name])])))
      // The measured round trip, shown next to the verdict. It is the real
      // elapsed time for THIS request - nothing is estimated or rounded down.
      setElapsedMs(Math.round(performance.now() - startedAt))

      // Tell the other screens the server has new data, so the dashboard and
      // history refetch instead of showing a stale total until a reload.
      announcePredictionCreated({ riskLevel: data.prediction })
    } catch (err) {
      // A failure belonging to a superseded submission is not this screen's
      // problem to report.
      if (id !== requestId.current) return

      const status = err?.status
      // `isNetworkError` covers "the request never got an answer". A timeout is
      // its own case: the client gave up waiting, which is a different message
      // from "the server is not running", and the interceptor reports it as
      // ECONNABORTED with a status of undefined.
      if (err?.isNetworkError || err?.isTimeout) {
        setError({
          kind: 'network',
          message:
            'Could not reach the AquaGuard AI server. Check your connection and that the backend is running, then try again.',
        })
      } else if (status === 422 || err?.errors) {
        // Field-level rejection: each message is shown against its own input.
        setError({
          kind: 'validation',
          message: errorMessage(err, 'One or more parameters are invalid.'),
        })
        if (err?.errors) setFieldErrors(err.errors)
      } else if (status === 401) {
        // There is no sign-in to send a visitor back to. A 401 here can only
        // mean a token that WAS sent and was rejected - which the open
        // application never issues - so the honest message names the actual
        // cause rather than inventing a session that does not exist.
        setError({
          kind: 'backend',
          message:
            'The server rejected a stored credential. This application has no sign-in, so clearing the site data and reloading will resolve it.',
        })
      } else if (status === 503) {
        setError({
          kind: 'backend',
          message:
            'The prediction model is unavailable on the server, so no verdict could be produced. That is a server-side problem, not a problem with your readings.',
        })
      } else {
        setError({
          kind: 'backend',
          message: errorMessage(err, 'The prediction could not be completed. Please try again.'),
        })
      }
    } finally {
      // Only the newest request is allowed to end the loading state; an older
      // one finishing would otherwise clear the spinner for a request still
      // genuinely in flight.
      if (id === requestId.current) setSubmitting(false)
    }
  }

  const risk = result?.prediction || result?.risk_level
  // Memoised because it is read on every render (the counter in the card
  // subtitle, the submit guard and the empty-state check) and only changes when
  // `values` does.
  const blanks = useMemo(() => findBlankFields(values), [values])
  const filledCount = FEATURE_NAMES.length - blanks.length

  return (
    <div>
      <PageHeader
        breadcrumb="Manual Prediction"
        title="Manual Prediction"
        description="Enter the five readings from your water test yourself. The trained model returns a safety verdict with a confidence score."
        // ONE LINE: the sentence is long enough that wrapping it made the header
        // two lines tall and pushed the form down. Clamped to a single line.
        oneLine
      />

      <div className="grid gap-6 lg:grid-cols-5">
        {/* --- Input cards --- */}
        <Card
          title="Sample parameters"
          subtitle={`All five readings are required · ${filledCount} of ${FEATURE_NAMES.length} entered`}
          className="lg:col-span-3"
          actions={
            <Link
              to={ROUTES.history}
              className="text-xs font-medium text-aqua-700 hover:underline dark:text-aqua-300"
            >
              View history
            </Link>
          }
        >
          <form onSubmit={handleSubmit} noValidate>
            {error && (
              <div
                role="alert"
                aria-live="polite"
                className={`mb-5 flex items-start gap-2 rounded-card border px-3.5 py-3 text-sm ${
                  error.kind === 'validation'
                    ? 'border-caution-light bg-caution-light/50 text-caution-dark dark:border-caution dark:bg-caution/10 dark:text-caution-light'
                    : 'border-unsafe-light bg-unsafe-light/50 text-unsafe-dark dark:border-unsafe dark:bg-unsafe/10 dark:text-unsafe-light'
                }`}
              >
                <Icon path={ICONS.info} className="mt-0.5 h-4 w-4 shrink-0" />
                {error.message}
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              {FEATURE_NAMES.map((name) => {
                const meta = FEATURE_META[name]
                const fieldError = fieldErrors[name]
                return (
                  <div
                    key={name}
                    className={`rounded-card border p-4 transition-colors focus-within:border-aqua-400 focus-within:bg-aqua-50/30 ${
                      fieldError ? 'border-unsafe-light bg-unsafe-light/20 dark:border-unsafe dark:bg-unsafe/10' : 'border-slate-200 dark:border-slate-700'
                    }`}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <label className="label mb-0" htmlFor={name}>
                        {meta.label}
                      </label>
                      <span className="text-2xs text-slate-400 tabular">
                        {meta.min}\u2013{meta.max}
                      </span>
                    </div>
                    <div className="relative mt-1">
                      <input
                        id={name}
                        name={name}
                        type="number"
                        inputMode="decimal"
                        step={meta.step}
                        min={meta.min}
                        max={meta.max}
                        value={values[name]}
                        onChange={handleChange}
                        disabled={submitting}
                        placeholder={meta.placeholder}
                        required
                        className={`input pr-14 tabular ${fieldError ? 'input-error' : ''}`}
                        aria-invalid={fieldError ? 'true' : undefined}
                        aria-describedby={fieldError ? `${name}-error` : undefined}
                      />
                      <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs font-medium text-slate-400">
                        {meta.unit}
                      </span>
                    </div>
                    {fieldError && (
                      <p id={`${name}-error`} className="field-error">
                        <Icon
                          path="M12 8v5m0 3h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"
                          className="mt-px h-3.5 w-3.5 shrink-0"
                        />
                        {fieldError}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>

            <div className="flex mt-5 flex-wrap items-center gap-2 border-t border-slate-100 pt-5 sm:gap-3 dark:border-slate-700">
              <Button
                type="submit"
                loading={submitting}
                icon={<Icon path={ICONS.predict} className="h-4 w-4" />}
              >
                {submitting ? 'Analysing…' : 'Analyze Water Quality'}
              </Button>
              {/* CLEAR IS A VISIBLE WHITE BUTTON WITH BLACK TEXT.

                  In dark mode `btn-secondary` is already white-on-dark, but the
                  card's colour remap in index.css lifts `text-slate-*` on a dark
                  surface — and on this LIGHT button that made the label vanish
                  until hover. `dark:text-black` pins the label to black so it is
                  readable at rest, not only under the pointer. */}
              <Button
                type="button"
                variant="secondary"
                onClick={handleReset}
                disabled={submitting}
                className="dark:bg-white dark:text-black dark:hover:bg-black dark:hover:text-white"
              >
                Clear
              </Button>
              <span className="ml-auto hidden text-xs text-slate-400 sm:block">
                {submitting ? 'Running the sample through the model…' : 'Five readings required'}
              </span>
            </div>
          </form>
        </Card>

        {/* --- Result panel --- */}
        <div className="space-y-6 lg:col-span-2">
          <Card title="Water Quality Result" subtitle="Appears after submission">
            {submitting ? (
              /* Loading state: the panel reports the wait rather than sitting
                 empty, or worse, showing the previous verdict as if it were new. */
              <div className="flex min-h-[16rem] flex-col items-center justify-center gap-3 text-center">
                <span className="h-8 w-8 animate-spin rounded-full border-2 border-aqua-500 border-t-transparent" />
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">Analyzing water quality…</p>
                <p className="max-w-xs text-xs text-slate-500">
                  Validating the readings, running the model and saving the result.
                </p>
              </div>
            ) : !result ? (
              <div className="flex min-h-[16rem] flex-col items-center justify-center gap-3 text-center">
                <span className="flex h-12 w-12 items-center justify-center rounded-full bg-aqua-50 text-aqua-600">
                  <Icon path={ICONS.predict} className="h-6 w-6" />
                </span>
                <div>
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-200">No result yet</p>
                  <p className="mt-1 max-w-xs text-xs text-slate-500">
                    The verdict and confidence score appear here once you submit a sample.
                  </p>
                </div>
              </div>
            ) : (
              <div className="animate-fade-in space-y-5">
                {/* --- WHERE THIS SAMPLE WAS TAKEN (prompt 4) ---
                    Shown whenever the sample came from a selected location, so
                    the verdict is never read against the wrong place. It states
                    the source exactly as the backend stored it: an identified
                    source type, or the nearest real nearby source with its real
                    distance, or an explicit "unavailable". Never a guess, and
                    never a source invented to complete the panel. */}
                {(carriedLocation || result.location_name || result.water_source_type) && (
                  <div className="rounded-card border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
                    <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Sampled at
                    </p>
                    <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                      {[carriedLocation?.name || result.location_name,
                        carriedLocation?.state || result.location_state,
                        carriedLocation?.country || result.location_country,
                      ]
                        .filter(Boolean)
                        .join(', ') || 'Selected location'}
                      {(carriedLocation?.pincode || result.location_pincode) ? (
                        <span> — Pincode: {(carriedLocation?.pincode || result.location_pincode)}</span>
                      ) : null}
                    </p>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {waterSourceLabel(
                        { ...(carriedLocation || {}), ...(result || {}) },
                        { empty: 'Water source information unavailable' },
                      )}
                    </p>
                  </div>
                )}
                {/* --- The verdict --- */}
                <div
                  className={`rounded-card border p-4 ${
                    risk === 'safe'
                      ? 'border-safe-light bg-safe-light/40 dark:border-safe dark:bg-safe/10'
                      : risk === 'unsafe'
                        ? 'border-unsafe-light bg-unsafe-light/40 dark:border-unsafe dark:bg-unsafe/10'
                        : 'border-caution-light bg-caution-light/40 dark:border-caution dark:bg-caution/10'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-2xs font-semibold uppercase tracking-wider text-slate-500">
                      Prediction
                    </p>
                    {/* COLOURED VERDICT: red unsafe, yellow moderate, green safe. */}
                    <Badge risk={risk} button />
                  </div>
                  <p
                    className={`mt-1.5 text-[1.75rem] font-bold uppercase leading-none tracking-tight ${
                      risk === 'safe'
                        ? 'text-safe-dark'
                        : risk === 'unsafe'
                          ? 'text-unsafe-dark'
                          : 'text-caution-dark'
                    }`}
                  >
                    {risk}
                  </p>
                  {/* THE RISK WORD. Mapped from the model's own verdict - safe ->
                      Low, moderate -> Medium, unsafe -> High - so it is a reading
                      of the real output, never a separately invented number. */}
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                    Risk: <span className="font-semibold">{RISK_WORDS[risk] || '—'}</span>
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Saved as prediction #{result.id}
                    {result.created_at ? ` · ${formatDate(result.created_at)}` : ''}
                    {/* The measured round trip for this request, so the user can
                        see how long the analysis actually took rather than being
                        told an estimate. */}
                    {elapsedMs > 0 ? ` · analysed in ${(elapsedMs / 1000).toFixed(2)}s` : ''}
                  </p>
                </div>

                {/* --- Confidence + the model's own class split ---
                    The confidence IS the probability of the predicted class —
                    the same number the backend stored — shown to one decimal so
                    a 84.6% never rounds into a misleading 85%. Beneath it, the
                    model's own per-class probabilities are shown verbatim, so
                    the user can see safe vs moderate vs unsafe exactly as the
                    forest voted rather than a single collapsed number. */}
                <div>
                  <div className="flex items-baseline justify-between">
                    <span className="text-2xs font-semibold uppercase tracking-wider text-slate-500">
                      Prediction Confidence
                    </span>
                    <span className="text-lg font-semibold text-slate-900 tabular dark:text-white">
                      {formatPercent(result.confidence, 1)}
                    </span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-700">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-aqua-500 to-aqua-600 transition-all duration-500"
                      style={{ width: `${Math.round((result.confidence || 0) * 100)}%` }}
                    />
                  </div>
                  <p className="mt-1.5 text-xs text-slate-400">
                    How strongly the model favours this verdict over the others.
                  </p>
                  {result.probabilities && (
                    <dl className="mt-3 grid grid-cols-3 gap-2">
                      {[
                        ['safe', RISK_LEVELS.safe],
                        ['moderate', RISK_LEVELS.moderate],
                        ['unsafe', RISK_LEVELS.unsafe],
                      ].map(([key, label]) => {
                        const raw = result.probabilities[key]
                        const pct =
                          raw == null || Number.isNaN(Number(raw))
                            ? null
                            : Number(raw) * 100
                        return (
                          <div
                            key={key}
                            className={`rounded-field border px-2 py-1.5 text-center ${
                              risk === key
                                ? 'border-aqua-300 bg-aqua-50 dark:border-aqua-700 dark:bg-aqua-900/40'
                                : 'border-slate-100 bg-slate-50 dark:border-slate-700 dark:bg-slate-800'
                            }`}
                          >
                            <dt className="text-2xs font-medium capitalize text-slate-500 dark:text-slate-400">
                              {label}
                            </dt>
                            <dd className="tabular text-sm font-semibold text-slate-800 dark:text-slate-100">
                              {pct == null ? '—' : `${pct.toFixed(1)}%`}
                            </dd>
                          </div>
                        )
                      })}
                    </dl>
                  )}
                </div>

                {/* --- Unsafe notice + route to alerts --- */}
                {risk === 'unsafe' && (
                  <div className="flex items-start gap-2 rounded-field bg-unsafe-light/50 px-3 py-2.5 text-xs text-unsafe-dark dark:border dark:border-unsafe dark:bg-unsafe/10 dark:text-unsafe-light">
                    <Icon path={ICONS.info} className="mt-px h-3.5 w-3.5 shrink-0" />
                    <span>
                      An alert has been created for this reading.{' '}
                      <Link to={ROUTES.alerts} className="font-semibold underline">
                        Open alerts
                      </Link>
                    </span>
                  </div>
                )}

                {/* --- The submitted readings --- */}
                <div className="border-t border-slate-100 pt-4 dark:border-slate-700">
                  <p className="mb-3 text-2xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    Parameters
                  </p>
                  <dl className="space-y-2 text-xs">
                    {FEATURE_NAMES.map((name) => {
                      // Prefer the SERVER's echo of what it stored, falling back to
                      // what was submitted, then the live field value.
                      const serverValue = result.parameters?.[name]?.value
                      return (
                        <div key={name} className="flex items-center justify-between gap-3">
                          <dt className="text-slate-500">{FEATURE_META[name].label}</dt>
                          <dd className="font-medium text-slate-800 tabular dark:text-slate-100">
                            {formatNumber(serverValue ?? submitted?.[name] ?? values[name])}
                            <span className="ml-1 font-normal text-slate-400">
                              {FEATURE_META[name].unit}
                            </span>
                          </dd>
                        </div>
                      )
                    })}
                  </dl>
                </div>

                {/* --- The disclaimer ----------------------------------------- */}
                {/* The exact sentence the brief specifies. It sets the same
                    expectation the model's own design does: this is an AI
                    estimate, not a laboratory certificate. */}
                <p className="border-t border-slate-100 pt-4 text-xs italic text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  {
                    'AI-based prediction. This result is not a substitute for certified laboratory water testing.'
                  }
                </p>
              </div>
            )}
          </Card>

          {/* --- Explanation --- */}
          {result && !submitting && (
            <Card title="What this means" subtitle="Based on the readings you submitted">
              <PredictionExplanation result={result} values={submitted} />
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
