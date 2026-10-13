/**
 * Explanation area for a prediction.
 *
 * Everything shown here is derived from the numbers the model actually
 * returned — the verdict, the confidence and the per-class probabilities. No
 * sentence is written unless the data behind it exists, and the component says
 * so plainly when it does not. There is no placeholder "analysis" text, because
 * anything invented here would read as a measurement the model never made.
 *
 * What each source of truth is:
 *   - verdict + confidence + probabilities: from POST /predictions/predict
 *   - safe ranges and labels: from the backend's parameter contract, mirrored
 *     in `FEATURE_META`, compared against the submitted values.
 */

import { FEATURE_META, FEATURE_NAMES } from '@/utils/constants'
import { formatNumber, formatPercent } from '@/utils/format'

/** Keyed copy so the wording lives with the component that uses it. */
const VERDICT_TEXT = {
  safe: {
    headline: 'This sample is classified as safe.',
    body: 'The model puts this sample in the safe class. Readings sit within the ranges typical of potable water.',
  },
  moderate: {
    headline: 'This sample is classified as moderate.',
    body: 'The model is not confident enough to call this sample safe. Some readings are borderline and are worth re-testing before the water is treated as potable.',
  },
  unsafe: {
    headline: 'This sample is classified as unsafe.',
    body: 'The model puts this sample in the unsafe class, and an alert has been raised for your account. Do not treat this water as potable on the strength of this reading alone.',
  },
}

/**
 * Which submitted readings fall outside the typical range for potable water.
 *
 * These are the backend's own bounds, so the page cannot disagree with what the
 * API would have rejected as invalid input. A reading inside the valid range can
 * still be a poor reading — that distinction is why this compares against a
 * narrower "typical" band rather than the hard limits.
 */
const TYPICAL = {
  ph: { min: 6.5, max: 8.5, label: 'pH', unit: 'pH' },
  turbidity: { min: 0, max: 5, label: 'Turbidity', unit: 'NTU' },
  tds: { min: 0, max: 600, label: 'Total Dissolved Solids', unit: 'mg/L' },
  temperature: { min: 0, max: 30, label: 'Temperature', unit: '\u00b0C' },
  dissolved_oxygen: { min: 6.5, max: 14, label: 'Dissolved Oxygen', unit: 'mg/L' },
}

function readingsOutsideTypicalRange(values) {
  return FEATURE_NAMES.reduce((out, name) => {
    const band = TYPICAL[name]
    const value = Number(values?.[name])
    if (!band || Number.isNaN(value)) return out
    if (value < band.min || value > band.max) {
      out.push({
        name,
        label: band.label,
        unit: band.unit,
        value,
        note: value < band.min ? `below the typical ${band.min}` : `above the typical ${band.max}`,
      })
    }
    return out
  }, [])
}

export default function PredictionExplanation({ result, values }) {
  if (!result) return null

  const verdict = result.prediction || result.risk_level
  const text = VERDICT_TEXT[verdict]
  const outside = readingsOutsideTypicalRange(values)
  const probabilities = result.probabilities || {}

  // Ordered strongest first so the panel leads with the model's main opinion.
  const ranked = Object.entries(probabilities)
    .filter(([, value]) => typeof value === 'number')
    .sort((a, b) => b[1] - a[1])

  const margin = ranked.length >= 2 ? ranked[0][1] - ranked[1][1] : null

  return (
    <div className="space-y-4 text-sm">
      {/* --- What the model concluded --- */}
      <div>
        <p className="font-medium text-slate-800">{text?.headline || 'Prediction complete.'}</p>
        <p className="mt-1 leading-relaxed text-slate-600">{text?.body}</p>
      </div>

      {/* --- How strongly, stated in the model's own terms --- */}
      {margin !== null && (
        <p className="leading-relaxed text-slate-600">
          The leading class holds{' '}
          <span className="font-medium tabular text-slate-700">
            {(ranked[0][1] * 100).toFixed(1)}%
          </span>{' '}
          of the probability mass, a margin of{' '}
          <span className="font-medium tabular text-slate-700">
            {(margin * 100).toFixed(1)} points
          </span>{' '}
          over the next class.
          {margin < 0.15 &&
            ' That margin is narrow, so treat this verdict as a close call rather than a firm one.'}
        </p>
      )}

      {/* --- Which readings drove it --- */}
      {outside.length > 0 ? (
        <div>
          <p className="font-medium text-slate-800">
            Readings outside the typical potable range
          </p>
          <ul className="mt-2 space-y-1">
            {outside.map((item) => (
              <li key={item.name} className="flex items-start gap-2 text-slate-600">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-caution" aria-hidden="true" />
                <span>
                  <span className="font-medium text-slate-700">{item.label}</span>{' '}
                  measured {formatNumber(item.value)} {item.unit}, {item.note}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-slate-600 dark:text-slate-300">
          Every submitted reading sits within the typical range for potable water.
        </p>
      )}

      {/* --- Honest limits of the answer --- */}
      <div className="rounded-field border-slate-100 bg-slate-50 p-3 text-xs leading-relaxed text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
        <p>
          This verdict comes from the trained Random Forest model
          {result.model_version ? ` (${result.model_version})` : ''}, evaluated on the five
          readings above. It is a statistical judgement about water quality, not a laboratory
          result, and it is not a substitute for certified testing.
        </p>
        {result.feature_contributions?.length > 0 && (
          <p className="mt-2">
            The readings the model weights most heavily are{' '}
            {[...result.feature_contributions]
              .sort((a, b) => b.importance - a.importance)
              .slice(0, 2)
              .map((item) => FEATURE_META[item.name]?.label || item.name)
              .join(' and ')}
            .
          </p>
        )}
      </div>

      {ranked.length > 1 && (
        <p className="text-2xs text-slate-400 tabular">
          Class probabilities:{' '}
          {ranked.map(([name, value]) => `${name} ${formatPercent(value)}`).join(' · ')}
        </p>
      )}
    </div>
  )
}
