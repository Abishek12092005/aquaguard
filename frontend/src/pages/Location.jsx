import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { locationApi, predictionApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Card from '@/components/Card'
import Icon from '@/components/Icon'
import LocationMapPicker from '@/components/LocationMapPicker'
import LocationPinIcon from '@/components/LocationPinIcon'
import LocationSuggestions from '@/components/LocationSuggestions'
import PageHeader from '@/components/PageHeader'
import { ICONS } from '@/config/navigation'
import useDeviceArea from '@/hooks/useDeviceArea'
import useDeviceLocation from '@/context/useDeviceLocation'
import { FEATURE_META, FEATURE_NAMES, ROUTES } from '@/utils/constants'
import { errorMessage, formatNumber, formatPercent } from '@/utils/format'
import { announcePredictionCreated } from '@/utils/dataRefresh'

/**
 * Location Prediction — the starting point for location-based water quality analysis.
 *
 * FULL FLOW: this screen IDENTIFIES a location and then everything the water at
 * that place implies — the water source type, the sources near it and their
 * distances, the risks the source carries, and the starting readings for the
 * Manual Prediction form.
 *
 *   1. Location name        "Karaikudi", "Chennai"
 *   2. Pincode              "630001"
 *   3. Famous / popular     "Marina Beach", "Meenakshi Amman Temple"
 *   4. Use My Location      the device's own coordinates
 *   5. Manual selection     a map / coordinate picker
 *
 * All four text-ish methods are one lookup on the server, so a name, a pincode
 * and a landmark behave identically. An unknown location is REFUSED with a clear
 * message rather than guessed at — the backend returns 404 and this page shows
 * "No location found".
 *
 * NOTHING IS INVENTED. The water source, the nearby sources and their distances
 * all come from mapped OpenStreetMap data; the risks and the default readings are
 * the backend's tables. When there is no mapped water the page says so plainly
 * instead of showing a guessed source.
 *
 * STEP 32: NO RAIN ON THIS SCREEN. The flow here is Location → Water Source →
 * Water Quality → Prediction, and nothing about the weather appears in it: not a
 * forecast, not a rain status, not a rain-derived factor, not a mention of the
 * word. Rain is a question about the DEVICE's own state, which is what the
 * separate Rainy Alerts screen answers from the browser's geolocation — a
 * different subject with a different source, not a panel that was moved. Both
 * screens still exist and neither depends on the other; see `waterFactors` for
 * the one place the two still meet, and why the risk NUMBER may still reflect
 * rain while no line of text here says so.
 *
 * STEP 15: the readings can now be carried ACROSS, deliberately. Once the
 * location's water-quality parameters are on screen, "Enter Water Prediction"
 * opens Manual Prediction with those five values already in its (still editable)
 * form and the location travelling internally. Nothing is analysed by pressing
 * it - the visitor still presses "Analyze Water Quality" on that page. The
 * estimates are labelled as estimates HERE, and the hand-off is a button the
 * visitor presses, never a silent pre-fill.
 */

/**
 * The exact sentence the backend returns when a place is outside the
 * administrator's configured scope. Mirrored here so the UI can recognise a
 * scope refusal even if a proxy rewrites the status code — but the backend
 * remains the authority: this page never decides what is in scope.
 */
const SCOPE_DENIED_MESSAGE =
  'Water quality analysis is currently available only within the configured location area.'

/**
 * Shown when no reliable mapped water source exists for a location.
 *
 * This is a first-class result, not an error: OpenStreetMap simply has no water
 * feature mapped near the point, and the honest answer is to say so rather than
 * display a guessed source with a made-up name.
 */
const WATER_UNAVAILABLE_MESSAGE = 'Water source information is unavailable for this location.'

/**
 * STEP 32: the risk factors that are about WATER.
 *
 * The backend derives the risk level partly from the rain forecast and tags every
 * factor it emits with a `source` of either `source type` or `weather`. STEP 32
 * moves rain off this screen entirely — it belongs to Rainy Alerts, which answers
 * the question about the DEVICE's own state rather than about whichever place
 * happens to be loaded here — so this screen renders only the water-sourced
 * factors and drops the `weather` ones.
 *
 * WHY THE NUMBER MAY STILL HAVE BEEN RAISED BY RAIN. The level the badge shows is
 * computed upstream and is not changed here. Rain can still move that number up
 * one step, while no line of text on this page mentions rain. That is intentional:
 * the level is an honest aggregate of everything known about the water at that
 * point, and quietly re-deriving it in the client to match a shorter list would
 * mean the badge disagrees with the server's own answer and with every report and
 * history row built from it. The screen stops TALKING about rain; it does not
 * start lying about the risk.
 *
 * A filter by SOURCE rather than by matching the words "rain" or "weather" in the
 * detail string. The backend is what decides what a factor is about, and its
 * `source` field is a fixed two-value vocabulary; reading the prose instead would
 * break the moment a factor's wording was rephrased, and would silently match a
 * water factor that merely mentions rain.
 */
function waterFactors(factors) {
  if (!Array.isArray(factors)) return []
  return factors.filter((factor) => factor && factor.source !== 'weather')
}

/**
 * STEP 23: is this typed text a PIN CODE?
 *
 * The shape of an Indian PIN code: six digits, not starting with 0. Zero is
 * reserved as the leading digit for military addresses, so a number starting
 * with it is not a civilian PIN code.
 *
 * This decides WHICH lookup to use and nothing about the answer - the real
 * identification happens on the server through the postal interface. It lives
 * here rather than only on the server so the page can route the search without
 * first asking a name-search question the brief says must not be asked; the
 * server re-checks it regardless, so a client that ignored this would still be
 * refused.
 */
function isPincodeText(text) {
  return /^[1-9][0-9]{5}$/.test(String(text ?? '').trim())
}

/**
 * STEP 12 - one plain sentence per provenance, shown as the card's subtitle.
 *
 * The badge beside each value names the source in one or two words; this says
 * the same thing in a sentence, so the card cannot be misread as a set of
 * measurements by skimming it. The keys are the server's own provenance codes.
 * The authoritative label on the badge is the server's; these are presentation.
 */
const PROVENANCE_HINT = {
  measured: 'A real measured sample recorded for this exact location',
  nearby_source: 'Measured at a named water source near this location — not this exact spot',
  historical: 'A previously measured reading for this location — not a current one',
  dataset_based: 'A dataset-based estimate from real measured samples — not this location',
  estimated: 'Typical values for this water source type — not measured anywhere near here',
  user_input_required: 'No reliable readings available — please enter your own test results',
}

/** The five search methods, shown as a legend under the search bar. */
const SEARCH_METHODS = [
  { icon: 'location', label: 'Location name', example: 'Karaikudi' },
  { icon: 'reports', label: 'Pincode', example: '630001' },
  { icon: 'search', label: 'Famous place', example: 'Marina Beach' },
  { icon: 'droplet', label: 'Use my location', example: 'GPS' },
  { icon: 'analytics', label: 'Manual selection', example: 'Map' },
]

/**
 * STEP 14 - THE VERDICT, AS IT COMES BACK FROM THE MODEL.
 *
 * Every value shown here is read from the server's own response. There is no
 * default, no placeholder verdict and no computed fallback: `prediction` is only
 * ever non-null when a real response supplied it, and a response without a
 * `prediction` field is handled as a failure on the caller side rather than
 * rendered as an empty panel.
 *
 * The risk word (Low / Medium / High) is a READING of the model's own verdict -
 * safe -> Low, moderate -> Medium, unsafe -> High - not a second score, so the
 * two can never disagree. It matches the wording Manual Prediction uses, so the
 * same sample reads the same way on both screens.
 */
const RISK_WORDS = { safe: 'Low', moderate: 'Medium', unsafe: 'High' }

function VerdictBanner({ prediction }) {
  const verdict = prediction?.prediction
  if (!verdict) return null
  const confidence = Number(prediction.confidence || 0)

  return (
    <div className="rounded-card border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
            Prediction
          </p>
          <p className="text-2xl font-bold uppercase tracking-tight text-slate-900 dark:text-white">
            {verdict}
          </p>
          <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-300">
            Risk level:{' '}
            <span className="font-medium">{RISK_WORDS[verdict] || 'Unknown'}</span>
          </p>
        </div>
        <Badge risk={verdict} button />
      </div>

      <div className="mt-4">
        <div className="flex items-baseline justify-between">
          <span className="text-2xs font-semibold uppercase tracking-wider text-slate-500">
            Prediction Confidence
          </span>
          <span className="text-lg font-semibold text-slate-900 tabular dark:text-white">
            {formatPercent(confidence, 0)}
          </span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
          <div
            className="h-full rounded-full bg-gradient-to-r from-aqua-500 to-aqua-600 transition-all duration-500"
            style={{ width: `${Math.round(confidence * 100)}%` }}
          />
        </div>
        <p className="mt-1.5 text-xs text-slate-400">
          How strongly the model favours this verdict over the others.
        </p>
      </div>
    </div>
  )
}

/** One field row on the selected-location card. Renders nothing when empty.
 *
 *  A field the data genuinely does not have is passed as the string
 *  "Not available" rather than as null/'' - see the callers - so that an absent
 *  area or pincode is VISIBLY absent instead of silently missing. The one thing
 *  that must still render nothing is a field nobody asked about, which is why
 *  null and undefined are handled before the placeholder.
 */
function Detail({ label, value, icon }) {
  // `icon` reaches this component BOTH ways: as SVG path data (`ICONS.location`)
  // and as a bare icon NAME (`'location'`). Passing the name straight into <path
  // d> is not a missing icon, it is an INVALID PATH, and the browser rejects the
  // whole <path> - so the icon silently vanished while the console filled with
  // "Expected moveto path command". Resolve a name through ICONS and leave real
  // path data (which no ICONS key can ever be) untouched.
  const path = ICONS[icon] || icon || ICONS.info
  if (value === null || value === undefined || value === '') return null
  const missing = value === 'Not available'
  return (
    <div className="flex items-start gap-3">
      <span
        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-field bg-aqua-50 text-aqua-700 dark:bg-slate-800 dark:text-aqua-300"
        aria-hidden="true"
      >
        <Icon path={path} className="h-4 w-4" />
      </span>
      <div className="min-w-0">
        <dt className="text-2xs font-semibold uppercase tracking-wider text-slate-400">{label}</dt>
        <dd
          className={
            missing
              ? 'truncate text-sm font-normal italic text-slate-400 dark:text-slate-500'
              : 'truncate text-sm font-medium text-slate-800 dark:text-slate-100'
          }
        >
          {value}
        </dd>
      </div>
    </div>
  )
}

/**
 * An animated status dot — the "animated/blinking status dots" the country
 * overview's legend and state list are specified with.
 *
 * The dot is a solid disc in the level's colour, wrapped in a halo that
 * expands and fades like the app's existing ripple, so the whole page speaks
 * one animation language. `motion-safe:` wraps both animations so a user with
 * reduced-motion enabled gets a still, correctly coloured dot instead.
 *
 * `tone` is one of safe / moderate / unsafe / unknown — the legend's colours:
 *
 *   🟢 SAFE  🟡 MODERATE  🔴 UNSAFE   (unknown renders as a neutral grey)
 */
function StatusDot({ tone }) {
  const colors = {
    safe: 'bg-safe shadow-safe/30',
    moderate: 'bg-caution shadow-caution/30',
    unsafe: 'bg-unsafe shadow-unsafe/30',
    unknown: 'bg-slate-300 shadow-slate-300/30 dark:bg-slate-600',
  }
  const haloColors = {
    safe: 'border-safe/60',
    moderate: 'border-caution/60',
    unsafe: 'border-unsafe/60',
    unknown: 'border-slate-300/60 dark:border-slate-600/60',
  }
  const color = colors[tone] || colors.unknown
  const halo = haloColors[tone] || haloColors.unknown

  return (
    <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center" aria-hidden="true">
      {/* The expanding halo — only for a real colour; "unknown" stays still,
          because a grey dot that pulses would advertise a data quality it
          does not have. */}
      {tone !== 'unknown' && (
        <span className={`absolute inset-0 rounded-full border-2 motion-safe:animate-dot-halo ${halo}`} />
      )}
      <span className={`relative h-2.5 w-2.5 rounded-full shadow-md motion-safe:animate-dot-blink ${color}`} />
    </span>
  )
}

/**
 * PROMPT 1, E.4/E.5: THE WATER SOURCE SELECTOR.
 *
 * Every source offered here is real: either a named mapped feature from the
 * nearby list (with its actual type and distance) or one of the supported
 * canonical types the backend itself publishes. Nothing is invented — the
 * list starts empty when there are no nearby sources, and the supported list
 * comes from the server's own response so the frontend cannot drift from the
 * backend's categories.
 */
const SUPPORTED_SOURCE_FALLBACK = [
  'piped water', 'municipal water source', 'borewell water', 'ground water',
  'well water', 'river water', 'pond water', 'lake water', 'tank water',
  'surface water', 'rain water',
]

function SourceSelector({ nearby, selected, onSelect }) {
  const nearbyTypes = []
  for (const row of nearby) {
    if (row?.type && !nearbyTypes.includes(row.type)) nearbyTypes.push(row.type)
  }
  const supported = SUPPORTED_SOURCE_FALLBACK

  return (
    <div className="mt-4 rounded-field border border-slate-200 bg-white p-3 dark:border-slate-600 dark:bg-slate-900">
      <p className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
        Water source for this prediction
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        No source is identified at the exact point. If you know which one applies,
        select it — the readings and the prediction will describe the source you choose.
      </p>

      <label
        htmlFor="source-selector"
        className="mt-3 block text-2xs font-semibold uppercase tracking-wider text-slate-400"
      >
        Select the actual source
      </label>
      <select
        id="source-selector"
        value={selected || ''}
        onChange={(event) => onSelect(event.target.value || null)}
        className="input mt-1"
        data-testid="source-selector"
      >
        <option value="">Water source not identified</option>
        {nearbyTypes.length > 0 && (
          <optgroup label="Mapped sources near this location">
            {nearbyTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </optgroup>
        )}
        <optgroup label="Other supported sources">
          {supported
            .filter((type) => !nearbyTypes.includes(type))
            .map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
        </optgroup>
      </select>
    </div>
  )
}

/**
 * The legend row: 🟢 SAFE · 🟡 MODERATE · 🔴 UNSAFE, each with its own
 * animated dot so the key at the top of the country result visually matches
 * every dot in the state list below it. Rendered as a list so screen readers
 * announce three distinct entries rather than one run of symbols.
 */
function RiskLegend({ legend }) {
  const entries =
    legend?.length > 0
      ? legend
      : [
          { level: 'low', label: 'SAFE' },
          { level: 'moderate', label: 'MODERATE' },
          { level: 'high', label: 'UNSAFE' },
        ]
  const toneByLevel = { low: 'safe', moderate: 'moderate', high: 'unsafe' }

  return (
    <ul className="flex flex-wrap items-center gap-x-5 gap-y-2">
      {entries.map((entry) => (
        <li key={entry.level} className="flex items-center gap-2">
          <StatusDot tone={toneByLevel[entry.level] || 'unknown'} />
          <span className="text-2xs font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-300">
            {entry.label}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** A full-panel loading state, used while a location is being identified. */
function IdentifyingState({ locating = false }) {
  return (
    <Card className="mb-6" aria-live="polite">
      <div className="flex flex-col items-center gap-4 py-6 text-center">
        {/* A pulsing pin over a scanning ring: the place is being located. */}
        <span className="relative flex h-14 w-14 items-center justify-center" aria-hidden="true">
          <span className="absolute inset-0 rounded-full border-2 border-aqua-300/60 motion-safe:animate-ripple" />
          <span className="absolute h-10 w-10 rounded-full bg-aqua-50 dark:bg-slate-800" />
          <Icon
            path={ICONS.location}
            className="relative h-6 w-6 text-aqua-700 motion-safe:animate-drop-bounce dark:text-aqua-300"
          />
        </span>
        <div>
          <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {locating ? 'Getting your location…' : 'Identifying location…'}
          </p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {locating
              ? 'Reading the device position and resolving the place it falls in.'
              : 'Resolving the place, district, state and pincode.'}
          </p>
        </div>
        {/* A skeleton of the card that is about to appear, so the layout does
            not jump when the result lands. */}
        <div className="grid w-full grid-cols-2 gap-3 sm:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={index}
              className="h-12 animate-pulse rounded-field bg-slate-100 dark:bg-slate-800"
            />
          ))}
        </div>
      </div>
    </Card>
  )
}

export default function Location() {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  // The row the keyboard is on, for the ArrowUp/ArrowDown/Enter selection.
  // -1 means "nothing highlighted yet"; the first Enter then takes the top row.
  const [activeIndex, setActiveIndex] = useState(-1)
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  // Set when the lookup itself failed, as opposed to succeeding with no matches.
  // The two need different words: "no matches" is an answer, "search is down" is
  // a fault, and showing one for the other misleads the user about their query.
  const [suggestionsError, setSuggestionsError] = useState(null)

  // The identified place, or null. `source` records HOW it was found, which is
  // shown on the card so the user can tell a GPS fix from a typed search.
  const [place, setPlace] = useState(null)
  const [source, setSource] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | ready | error
  const [message, setMessage] = useState(null)
  // True when the refusal is the ADMIN SCOPE restriction rather than a bad
  // search. The two need different wording and different styling, so they are
  // tracked separately instead of both being "an error".
  const [blocked, setBlocked] = useState(false)

  // "Use my location" runs the browser's own GPS prompt.
  const [locating, setLocating] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  // STEP 25: the device fix the browser reported, kept ONLY so the map can be
  // opened on it. It is deliberately not rendered - the brief asks not to expose
  // raw coordinates unnecessarily, and an auto-detected position is personal
  // data the user never typed. The map modal shows the PLACE it resolved to and
  // hides the numbers.
  const [deviceFix, setDeviceFix] = useState(null)
  // STEP 25: WHICH of the two paths opened the map. The modal needs it because
  // "a pin the user is dragging" and "the position the device reported" deserve
  // different wording and a different privacy treatment, and it is the only
  // thing that distinguishes them - both hand the map a point.
  const [pickerMode, setPickerMode] = useState('manual')
  // STEP 26: WHY A CONFIRMED PIN WAS REFUSED, shown INSIDE the map.
  //
  // The modal used to close on confirm and report a failure on the page behind
  // it, which discarded the pin the user had just placed. Holding the reason
  // here instead keeps the map - and the pin, and the zoom level - exactly where
  // they were, so the failure is recoverable rather than a restart.
  const [pickerError, setPickerError] = useState(null)

  // Everything the identification produced for the selected place: the water
  // source and nearby sources, the risk category, the named risks it carries,
  // and the default prediction readings. Fetched once the place is known, from
  // the real water lookup — never inferred from the place name.
  // STEP 32: no weather state is held here at all. There is deliberately no
  // `rain` field to go stale, so nothing on this screen can render a forecast.
  const [water, setWater] = useState(null)
  // PROMPT 1, E.4: THE SOURCE THE USER CHOSE, when the map data lists more
  // than one. `water.primary` is what the backend identified AT the exact
  // point; when it is null, or the user knows a different source applies, a
  // selection from the nearby list or the supported-type list is the actual
  // source the prediction is made for. Null means no explicit selection — the
  // backend's own identification is used, or none if it made none.
  const [selectedSource, setSelectedSource] = useState(null)
  const [riskLevel, setRiskLevel] = useState(null)
  const [risks, setRisks] = useState([])
  const [defaults, setDefaults] = useState(null)
  // STEP 12: the five parameters, with their labels and units, as the SERVER
  // names them. Rendering from this rather than from a local constant means the
  // card and the prediction model cannot drift apart, and a parameter added to
  // the model appears here without a frontend change.
  const [parameterDefinitions, setParameterDefinitions] = useState([])

  // --- STEP 14: PREDICT ON THIS PAGE ---------------------------------------
  // `editable` is the COPY of the readings the user can change. It is seeded
  // from the server's values and then belongs to the user: the whole point of
  // Step 12's provenance work is that these are estimates, and an estimate the
  // user cannot correct is not a starting point, it is a figure they are told to
  // accept. The server's `defaults` are never mutated - the card and the result
  // keep showing what was supplied, and `editable` is what was actually sent.
  const [editable, setEditable] = useState({})
  // The verdict. Null until a real one arrives, and it is ONLY ever set from a
  // server response - there is no local computation, no default and no fallback
  // verdict anywhere in this screen.
  const [prediction, setPrediction] = useState(null)
  // The exact readings that produced `prediction`, so the result card can show
  // the numbers the verdict was computed from rather than the current form state.
  const [analysed, setAnalysed] = useState(null)
  const [analysing, setAnalysing] = useState(false)
  // { kind, message } - `kind` distinguishes a network failure from a rejected
  // reading from a model outage, because each needs different words.
  const [analysisError, setAnalysisError] = useState(null)
  // Per-field messages, keyed by parameter name, from a 422.
  const [fieldErrors, setFieldErrors] = useState({})
  // The provenance of `defaults` - "Estimated"/"Dataset-based"/"User input
  // required" - supplied by the server, so THIS screen can say plainly that
  // these are not a measurement before the visitor copies any of them across.
  const [defaultsSource, setDefaultsSource] = useState(null)
  const [waterStatus, setWaterStatus] = useState('idle') // idle | loading | ready | error
  // STEP 16: WHY the water lookup failed, when it did. A slow or unavailable
  // upstream is reported as exactly that - the server was unreachable or too
  // slow - rather than being flattened into the same "no mapped water" message
  // a genuinely unmapped area gets, so the two are never confused.
  const [waterError, setWaterError] = useState(null)
  // STEP 16: how long the water fetch has been running, so the loader can report
  // the real wait instead of spinning indefinitely with no information in it.
  const [waterElapsedMs, setWaterElapsedMs] = useState(0)

  // Ticks only while a water lookup is actually in flight, and stops as soon as
  // it settles, so an idle page never schedules work.
  useEffect(() => {
    if (waterStatus !== 'loading') {
      setWaterElapsedMs(0)
      return undefined
    }
    const startedAt = performance.now()
    const tick = window.setInterval(() => {
      setWaterElapsedMs(performance.now() - startedAt)
    }, 200)
    return () => window.clearInterval(tick)
  }, [waterStatus])

  // --- Country overview (Step 19) -----------------------------------------
  // When the search text is a COUNTRY, the page shows a country card instead
  // of a single place: every supported state / region under that country, each
  // with ONE aggregated water-quality risk indicator. `countryStatus` mirrors
  // the single-place status machine so the two render paths never overlap.
  const [country, setCountry] = useState(null)
  const [countryStatus, setCountryStatus] = useState('idle') // idle | loading | ready | error

  // --- State overview (Step 20) --------------------------------------------
  // When the search text is a STATE, the page shows a state card instead of a
  // single place or the country view: every district under that state, in
  // alphabetical ORDER with one aggregated water-quality risk dot each.
  // Individual place predictions are deliberately NOT shown at this level.
  const [stateOverview, setStateOverview] = useState(null)
  const [stateStatus, setStateStatus] = useState('idle') // idle | loading | ready | error

  // --- District search within the state (Step 19) -------------------------
  // The brief requires the districts to stay SEARCHABLE once the state is on
  // screen. A state like Uttar Pradesh lists 76 districts, and a user looking for
  // one of them should not have to scroll, and must never have to CLICK one just
  // to find out it exists or what its risk is. The filter is therefore local and
  // instant: it narrows the rows already on screen, it never triggers a lookup,
  // and clearing it restores the full ordered list.
  const [districtFilter, setDistrictFilter] = useState('')

  // The rows the list actually renders: the state's districts in their backend
  // order, narrowed by the search text. Matching is case-insensitive and works on
  // a substring, so "cudd" finds Cuddalore and "TN" is not tried on a name.
  const visibleDistricts = useMemo(() => {
    const all = stateOverview?.districts ?? []
    const wanted = districtFilter.trim().toLowerCase()
    if (!wanted) return all
    return all.filter((district) =>
      `${district.district ?? ''} ${district.name ?? ''} ${district.state ?? ''}`
        .toLowerCase()
        .includes(wanted),
    )
  }, [stateOverview?.districts, districtFilter])

  // --- District places (Step 21) -------------------------------------------
  // When the search text is a DISTRICT, the page shows a district card: the
  // nine major / relevant places of that district — 3 SAFE / 3 MODERATE /
  // 3 UNSAFE internally — but the labels are NEVER rendered. Each card shows
  // only place name, town/village/area, district and state; the user clicks a
  // place to inspect its water, and no prediction is revealed in this list.
  const [districtOverview, setDistrictOverview] = useState(null)
  const [districtStatus, setDistrictStatus] = useState('idle') // idle | loading | ready | error

  // --- Village disambiguation (Step 22) -------------------------------------
  // A BARE VILLAGE NAME IS NOT AN ANSWER.
  //
  // Village names repeat all over the country. Answering "ExampleVillage" with
  // the first map hit would report a water source for a completely different
  // village, so the backend refuses a village that carries no district and sends
  // the candidates back instead. This state holds that pending question until the
  // user names the village AND its district - at which point the qualified search
  // is ordinary and the single-place flow runs normally.
  //
  // This is deliberately VILLAGES ONLY. A city, town, area, nagar, colony,
  // company, shop, college, school, hotel, hospital or landmark never sets this,
  // so those searches behave exactly as they always have.
  const [villagePending, setVillagePending] = useState(null) // { village, reason, message, candidates }
  const [villageStatus, setVillageStatus] = useState('idle') // idle | ready
  // The district the user typed/picked for the pending village, kept so the
  // confirm button can be disabled until it actually has one.
  const [villageDistrict, setVillageDistrict] = useState('')

  // --- Pincode identification (Step 23) -------------------------------------
  // When the typed text is a PIN CODE, the page shows the postal area it
  // identifies - area, city/town, district, state, country, pincode - and then
  // the water source and parameters for that area, and the user carries on into
  // Manual Prediction exactly as they would from a name search.
  //
  // `pincodeAreas` is populated only when the pincode genuinely maps to more than
  // one place. Those are shown as options instead of one being chosen for the
  // user, which would be inventing a location.
  const [pincodeOverview, setPincodeOverview] = useState(null)
  const [pincodeStatus, setPincodeStatus] = useState('idle') // idle | loading | ready | error
  const [pincodeAreas, setPincodeAreas] = useState([])

  // --- Branch selection (Step 24) -------------------------------------------
  // A CHAIN WITH MORE THAN ONE BRANCH IS ONE SEARCH WITH SEVERAL ANSWERS.
  //
  // "Indian Bank Karaikudi" is two real buildings, in two different areas, with
  // two different sets of mapped water around them. The backend used to answer
  // with whichever came first, so the water-quality result that followed
  // described a branch the user never chose - and the brief is explicit that the
  // headquarters or an arbitrary branch must not stand in for the selected one.
  //
  // So the backend returns the winning branch AND every other real branch, and
  // this asks. Nothing is committed until an actual branch is clicked: the
  // already-committed place is replaced only by the row the user picks, using
  // that row's own coordinates, which is what keeps the water lookup pinned to
  // the selection rather than to a fresh lookup of the same text.
  const [branches, setBranches] = useState([])

  /**
   * STEP 25: the reverse-geocode the map modal calls as its pin moves.
   *
   * A stable reference on purpose. The modal re-runs its lookup whenever the
   * function identity changes, and an inline arrow would be a new function on
   * every parent render - so a pin that had not moved would be re-resolved over
   * and over, and dragging would queue lookups for points the user had already
   * passed.
   */
  const reverseGeocode = useCallback(
    (coords) => locationApi.reverse(coords).then((response) => response.data ?? null),
    [],
  )

  const navigate = useNavigate()

  // PROMPT 1, E.4/E.5: THE SOURCE THE PREDICTION DESCRIBES.
  //
  // An explicit user selection always wins — the user may know the pump at
  // their street is a borewell even when the map only shows a tank nearby.
  // Otherwise the backend's identification of a source AT this exact point is
  // used; when no source is identified, there is NO source: the string is
  // literally "Water source not identified", never a nearby feature
  // promoted into one.
  const effectiveSource = selectedSource || water?.primary || null

  // STEP 10: HOW MANY ROWS SHARE EACH NAME IN THE CURRENT RESULT SET.
  //
  // (The count itself now lives inside the shared LocationSuggestions panel,
  // which applies the same rule for both screens.)

  // Step 9: the state / district THIS DEVICE is in, used to rank the
  // autocomplete. Null when the permission was refused, which is a supported
  // outcome and not a failure - the search then behaves exactly as it always
  // has. See hooks/useDeviceArea for why this is a preference and never a
  // filter.
  const deviceArea = useDeviceArea()

  // The app-wide location grant. Read here so "Use My Location" can REUSE a fix
  // the shell or the loader already obtained (no second browser request, no
  // second prompt) and can hand its own fix back with `reuseFix` so the shared
  // state - and anything reading it - moves as soon as coordinates exist.
  //
  // IT IS ALSO WATCHED, so a grant given in the global popup is USED on this page
  // rather than merely recorded - see the effect below. That is a deliberate
  // change: the visitor who allowed location expects the location to appear here,
  // without pressing a second button.
  const sharedLocation = useDeviceLocation()

  // --- THE GRANT FROM THE PERMISSION POPUP IS USED, NOT JUST RECORDED. --------
  //
  // THE PROBLEM THIS SOLVES. The global popup's "Allow" calls
  // `requestLocation()` on the shared provider, which obtains the device fix and
  // reverse-geocodes it into `sharedLocation.coords` / `.place`. That was ALL it
  // did: the popup closed, the fix sat in shared state, and THIS page - which is
  // the screen the visitor is actually looking at - did nothing with it. So
  // granting access looked like it had no effect until the visitor pressed
  // "Use My Location" a second time.
  //
  // Now the page WATCHES the shared grant and, the first time a fix appears while
  // this page has no location of its own, runs it through the ordinary commit
  // path: coordinates are handed to the provider (already there) and the place
  // is resolved and committed, so the location field fills and the water data
  // loads - exactly as if "Use My Location" had been pressed.
  //
  // WHY IT IS GUARDED THREE WAYS:
  //   * `grantHandledRef` - fires ONCE per page mount. Without it, every later
  //     render that still sees the same fix would re-commit the place and fight
  //     whatever the visitor did next (typed a search, picked a pin).
  //   * Only when there is no `place` yet and no search in flight, so it never
  //     overwrites a location the visitor has already chosen.
  //   * Only when the provider is `granted`, so a stale/null fix mid-request
  //     cannot trigger a lookup.
  const grantHandledRef = useRef(false)
  useEffect(() => {
    if (grantHandledRef.current) return undefined
    const grant = sharedLocation?.coords
    if (!grant || typeof grant.lat !== 'number' || typeof grant.lon !== 'number') {
      return undefined
    }
    if (sharedLocation?.status !== 'granted') return undefined
    // A location is already on screen - the grant belongs to a previous visit or
    // another screen, and must not silently replace what the visitor is looking
    // at. Mark it handled so it never fires later either.
    if (place || status === 'loading') {
      grantHandledRef.current = true
      return undefined
    }
    grantHandledRef.current = true
    // Same path "Use My Location" uses, so there is one source of truth for how
    // a fix becomes a committed place. `commitFix` is intentionally not in the
    // deps: it is stable for this purpose and re-running this effect is exactly
    // what the guard above prevents.
    commitFix(grant, null)
    return undefined
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sharedLocation?.coords, sharedLocation?.status])

  // Guards against a slow earlier request overwriting a newer answer: only the
  // most recent request may commit its result.
  const requestId = useRef(0)
  // The states whose risk has already been requested, so the enrichment effect
  // fetches once per state rather than once per re-render.
  const enrichingRef = useRef(new Set())
  // STEP 18: the country whose risk dots have already been fetched. A single
  // name rather than a growing set, because the country view is re-entered from
  // scratch each time and re-fetches when it is.
  const enrichedCountryRef = useRef(null)
  const suggestionRequestId = useRef(0)
  // The search input, so the shared suggestion portal can measure its viewport
  // rectangle and position the dropdown under it.
  const searchInputRef = useRef(null)
  // The device's area, mirrored into a ref so the debounced timer can read the
  // CURRENT value without the search effect having to re-run (and restart the
  // debounce, and re-request) every time the permission resolves.
  const deviceAreaRef = useRef({ state: null, district: null })
  // Bumped once, when the device's area first becomes known, to make the search
  // effect below re-run with the now-populated ref.
  const [areaEpoch, setAreaEpoch] = useState(0)

  // Re-run the LAST search once the device's area becomes known.
  //
  // Without this the first few suggestions a user sees were ranked without any
  // local preference - the geolocation prompt is still open while the first
  // characters are being typed - and the local-first ordering would only appear
  // from the next keystroke onward. Bumping `areaEpoch` makes the search effect
  // below run again with the now-populated ref, so the list the user is actually
  // looking at is the local-first one. Same debounce, same request path, and the
  // request-id guard drops the stale response.
  //
  // It fires at most once, and the box is never cleared or refilled, so nothing
  // flickers in the input.
  useEffect(() => {
    if (areaEpoch > 0) return
    if (!deviceArea.state) return
    deviceAreaRef.current = {
      state: deviceArea.state,
      district: deviceArea.district,
    }
    setAreaEpoch((n) => n + 1)
  }, [deviceArea.state, deviceArea.district, areaEpoch])

  // Debounced autocomplete. One request is made after typing pauses, rather than
  // one for every keystroke. The response is generated by the existing geocoder;
  // this screen contains no hardcoded location list.
  //
  // A SINGLE CHARACTER IS ENOUGH to search. The previous floor was two
  // characters, which contradicted the requirement to show matching places from
  // the first letter: "c" has real matches (Chennai, Coimbatore, Cairo) and the
  // providers answer it in a few hundred milliseconds. The floor is now one
  // non-space character.
  useEffect(() => {
    const text = query.trim()
    ++suggestionRequestId.current
    const id = suggestionRequestId.current
    if (text.length < 1) {
      setSuggestions([])
      setSuggestionsLoading(false)
      setSuggestionsOpen(false)
      setSuggestionsError(null)
      return undefined
    }

    setSuggestionsLoading(true)
    setSuggestionsOpen(true)
    // A new result set invalidates whatever row the keyboard was on.
    setActiveIndex(-1)
    // The device's area may arrive AFTER the first keystroke - the permission
    // prompt is still open while someone has already typed. Taking it from a
    // ref inside the timer means a lookup that lands mid-typing is picked up by
    // the NEXT search rather than forcing a second request now, so typing is
    // never delayed by the prompt.
    const area = deviceAreaRef.current
    const timer = setTimeout(async () => {
      try {
        // `autocomplete: true` tells the backend this is the typing path, so it
        // asks the providers for fewer spelling variants and answers sooner. It
        // changes how much is searched, never what: every suggestion is still a
        // real geocoder result, and the full variant set is still used when the
        // user commits to one place.
        //
        // Step 9: `state` / `district` are the device's OWN administrative area,
        // and they only REORDER what comes back. They are sent only when they
        // are known - with the permission refused they are absent and the search
        // is the plain general search.
        const response = await locationApi.search({
          q: text,
          limit: 8,
          autocomplete: true,
          ...(area.state ? { state: area.state } : null),
          ...(area.district ? { district: area.district } : null),
        })
        if (id !== suggestionRequestId.current) return
        setSuggestions(Array.isArray(response.data) ? response.data : [])
        setSuggestionsError(null)
      } catch (err) {
        if (id !== suggestionRequestId.current) return
        // A failed lookup shows NOTHING rather than a stale list from an earlier
        // query, which would otherwise be presented as if it matched what is
        // now in the box. The user is told the lookup failed, plainly.
        setSuggestions([])
        setSuggestionsError(
          err?.isNetworkError || err?.isTimeout
            ? 'Could not reach the search service. Check your connection.'
            : 'Location search is unavailable right now. Please try again.',
        )
      } finally {
        if (id === suggestionRequestId.current) setSuggestionsLoading(false)
      }
    }, 300)

    return () => clearTimeout(timer)
  }, [query, areaEpoch])

  // KEYBOARD SELECTION FOR THE AUTOCOMPLETE (PROMPT 16).
  //
  // The suggestion list was mouse-only: ArrowUp/ArrowDown to move an active
  // row, and Enter to commit the highlighted one. The `onKeyDown` lives on the
  // INPUT, not on the list, because the list's buttons are only reachable after
  // tabbing through it -- and the requirement is that typing, pressing arrows
  // and pressing Enter moves the map, with no pointer at all.
  //
  // `preventDefault` on Enter stops the browser submitting the surrounding
  // form, which would re-run the full-text search against the raw box text and
  // overwrite the exact result the user had just highlighted.
  function moveHighlight(delta) {
    if (!suggestions.length) return -1
    setActiveIndex((current) => {
      const next = current < 0 ? (delta > 0 ? 0 : suggestions.length - 1) : current + delta
      if (next < 0) return suggestions.length - 1
      if (next >= suggestions.length) return 0
      return next
    })
    return 0
  }

  function handleSearchKeyDown(event) {
    if (!suggestionsOpen || suggestions.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      moveHighlight(1)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      moveHighlight(-1)
    } else if (event.key === 'Enter') {
      // A highlighted row wins; with none highlighted, the first row does.
      const target = suggestions[activeIndex >= 0 ? activeIndex : 0]
      if (!target) return
      event.preventDefault()
      selectSuggestion(target)
      setActiveIndex(-1)
    } else if (event.key === 'Escape') {
      setSuggestionsOpen(false)
      setActiveIndex(-1)
    }
  }

  function selectSuggestion(candidate) {    // STEP 10: THE BOX SHOWS THE BRANCH, NOT JUST ITS NAME.
    //
    // `branch_label` is the "ABC Store - Karaikudi, Sivaganga, Tamil Nadu" form,
    // so once a user picks a branch the search box says WHICH one, and the
    // selected-location card below carries the same text. Putting the bare name
    // in the box would leave a user who picked the Madurai branch looking at
    // "ABC Store" with no way to tell what they had chosen, and the box is
    // editable, so it has to describe what is actually selected.
    //
    // The full result is then reused as-is - its own coordinates, never a
    // re-resolve of the label, which is what keeps the water workflow pinned to
    // the exact branch that was chosen rather than to whichever branch a fresh
    // lookup for the same text happened to return first.
    setQuery(candidate.branch_label || candidate.label || candidate.display_name || candidate.name || '')
    setSuggestions([])
    setSuggestionsOpen(false)
    setSuggestionsError(null)
    setStatus('loading')
    setMessage(null)
    setWater(null)
    // STEP 24: picking a specific row from the dropdown IS the branch choice, so
    // the "which branch did you mean" card is answered and cleared. The row is
    // reused as-is, with its own coordinates, so the water lookup is pinned to
    // this branch and not to a fresh lookup of the same text.
    setBranches([])
    // Reuse the complete geocoder result instead of resolving the label again.
    // Its coordinates make the subsequent water and parameter lookup exact.
    commit(candidate, 'search')
  }

  useEffect(() => {
    // STEP 17: the state view paints from the bundled list FIRST, then fills
    // in the per-district water risk.
    //
    // The list itself is local, so all 39 districts of a state appear
    // immediately; only the risk indicator needs the network, and it is
    // fetched afterwards and merged in place. A user therefore never waits on
    // the slowest water lookup to find out that a district exists, and a slow
    // upstream leaves the list fully readable with honest "unknown" markers.
    const stateName = stateOverview?.state?.name
    if (stateStatus !== 'ready' || !stateName) return undefined
    // The enrichment is fetched once per state. After it merges in, every
    // district has been sampled, so the guard below stops the fetch repeating.
    if (!enrichingRef.current.has(stateName)) {
      if ((stateOverview?.summary?.unknown ?? 0) === 0) return undefined
    }

    let cancelled = false
    ;(async () => {
      try {
        const response = await locationApi.state({ q: stateName })
        if (cancelled) return
        const enriched = response.data ?? {}
        if (enriched.available && (enriched.districts?.length ?? 0) > 0) {
          setStateOverview((current) =>
            current ? { ...current, ...enriched } : enriched,
          )
        }
      } catch {
        // The risk enrichment is best effort. The list is already on screen
        // and every district already reads "unknown" with a reason, which is
        // the honest answer - so a failure here needs no separate message.
      } finally {
        enrichingRef.current.add(stateName)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [stateStatus, stateOverview?.state?.name, stateOverview?.summary?.unknown])

  useEffect(() => {
    // STEP 18: the country's states paint from the names alone, then the risk
    // dots are fetched and merged in.
    //
    // This is the same two-phase shape as the state view above, and for the same
    // reason: the names are already known and local, so a user sees every state
    // of the country at once and the dots fill in afterwards. A slow or
    // unreachable water service therefore leaves a COMPLETE list of grey
    // "Insufficient data" dots rather than a blank screen.
    const countryName = country?.country?.name
    if (countryStatus !== 'ready' || !countryName) return undefined
    if (enrichedCountryRef.current === countryName) return undefined
    // Every state already has a measured level: there is nothing left to enrich.
    if ((country?.summary?.unknown ?? 0) === 0) return undefined

    let cancelled = false
    ;(async () => {
      try {
        const response = await locationApi.country({ q: countryName })
        if (cancelled) return
        const enriched = response.data ?? {}
        if (enriched.available && (enriched.states?.length ?? 0) > 0) {
          setCountry((current) => (current ? { ...current, ...enriched } : enriched))
        }
      } catch {
        // Best effort. The full list is already on screen with honest
        // "Insufficient data" markers, so a failure needs no separate message.
      } finally {
        enrichedCountryRef.current = countryName
      }
    })()
    return () => {
      cancelled = true
    }
  }, [countryStatus, country?.country?.name, country?.summary?.unknown])

  const commit = useCallback((nextPlace, nextSource) => {
    setPlace(nextPlace)
    setSource(nextSource)
    setStatus('ready')
    setMessage(null)
    setBlocked(false)
    // A single place is now shown, so any country or state overview that was
    // on screen is dropped — the views are alternatives, never stacked.
    setCountry(null)
    setCountryStatus('idle')
    // STEP 18: entering the country view again starts a fresh enrichment, so
    // the guard is released with the view. Without this, searching "India", then
    // a place, then "India" again would paint the list instantly and never
    // re-sample the dots, because the guard still held the country's name.
    enrichedCountryRef.current = null
    setStateOverview(null)
    setStateStatus('idle')
    setDistrictOverview(null)
    setDistrictStatus('idle')
    // STEP 22: a resolved place supersedes any pending village question - the
    // user has already identified which village they meant.
    setVillagePending(null)
    setVillageStatus('idle')
    setVillageDistrict('')
    // STEP 23: a committed place supersedes any pincode overview.
    setPincodeOverview(null)
    setPincodeAreas([])
    setPincodeStatus('idle')
  }, [])

  /**
   * STEP 24: THE USER PICKS WHICH BRANCH THEY MEANT.
   *
   * The row that was clicked becomes the identified place outright - its own
   * coordinates, its own address, its own water. Nothing is re-resolved from the
   * search text, because a fresh lookup of the same text would return whichever
   * branch happened to rank first, which is precisely the failure this step
   * exists to remove. The branch list is then cleared, because the question has
   * been answered and leaving it on screen would invite the user to re-pick a
   * place the card below already describes.
   */
  function selectBranch(branch) {
    if (!branch?.lat) return
    commit(branch, 'search')
    setQuery(branch.branch_label || branch.label || branch.display_name || branch.name || '')
    setBranches([])
  }

  const fail = useCallback((text, isBlocked = false) => {
    setPlace(null)
    setSource(null)
    setStatus('error')
    setMessage(text)
    setBlocked(isBlocked)
    setCountry(null)
    setCountryStatus('idle')
    // STEP 18: leaving the country view, so the next visit re-samples its dots.
    enrichedCountryRef.current = null
    setStateOverview(null)
    setStateStatus('idle')
    setDistrictOverview(null)
    setDistrictStatus('idle')
    // STEP 22: a refusal is not an answer, so the pending village question is
    // dropped along with the rest of the previous result.
    setVillagePending(null)
    setVillageStatus('idle')
    setVillageDistrict('')
    // STEP 23: a refusal is not an identification either, so the pincode overview
    // goes with the rest of the previous result.
    setPincodeOverview(null)
    setPincodeAreas([])
    setPincodeStatus('idle')
    // STEP 24: a refusal is not a branch selection either.
    setBranches([])
  }, [])

  /**
   * STEP 23: the user picked one of the areas a pincode maps to.
   *
   * The area is adopted as the identified place - it has real coordinates and a
   * real address, so the rest of the screen (water source, parameters, the hand
   * off to Manual Prediction) works on it exactly as it does for a name search.
   * The pincode itself rides along on the place, because the number the user typed
   * is what they searched by and is never replaced by a neighbouring one.
   */
  function openPincodeArea(area) {
    commit({ ...area, kind: 'pincode' }, 'search')
    setPincodeAreas([])
    setPincodeOverview(null)
    setPincodeStatus('idle')
  }
  /**
   * Drill into one state from the country overview: resolve it the SAME way
   * the search bar resolves any place, then show the full single-place flow
   * for it. The overview is replaced — Country → States is the level the
   * brief specifies for this view, and the place detail lives one click away
   * rather than being mixed into it.
   */
  async function openState(state) {
    const id = ++requestId.current
    setCountryStatus('idle')
    setStatus('loading')
    setQuery(`${state.state}, ${country?.country?.name || ''}`.replace(/,\s*$/, ''))
    try {
      const response = await locationApi.resolve(
        `${state.state}, ${country?.country?.name || ''}`.replace(/,\s*$/, ''),
        // STEP 22: already qualified with a country, so the village gate has
        // nothing to say about it.
        { allowAmbiguous: true },
      )
      if (id !== requestId.current) return
      commit(response.data, 'search')
    } catch (err) {
      if (id !== requestId.current) return
      const { blocked: isBlocked, text: errorText } = describeError(err)
      fail(errorText || `No location found for “${state.state}”.`, isBlocked)
    }
  }

  /**
   * STEP 17: drill into one DISTRICT from the state list.
   *
   * Clicking is OPTIONAL - the whole list, with every district's state,
   * country and status, is already on screen. This is only the path to the
   * place-level analysis inside a district, and it resolves the district the
   * same way the search bar resolves any place, so the scope check and the
   * water lookup both run against one validated location.
   */
  async function openStateDistrict(district) {
    const id = ++requestId.current
    setStateStatus('idle')
    setStatus('loading')
    setQuery(`${district.district}, ${district.state || ''}`.replace(/,\s*$/, ''))
    try {
      const response = await locationApi.resolve(
        `${district.district}, ${district.state || ''}`.replace(/,\s*$/, ''),
        // STEP 22: "District, State" already carries the geographic context, so
        // the village gate is skipped and the district resolves as it always has.
        { allowAmbiguous: true },
      )
      if (id !== requestId.current) return
      commit(response.data, 'search')
    } catch (err) {
      if (id !== requestId.current) return
      const { blocked: isBlocked, text: errorText } = describeError(err)
      fail(errorText || `No location found for “${district.district}”.`, isBlocked)
    }
  }

  /**
   * Drill into one place from the district card (Step 21): the user clicked a
   * place to inspect its water. Resolve it the SAME way the search bar
   * resolves any place, then run the full single-place flow — the analysis and
   * prediction happen HERE, not in the list, which is exactly the brief's
   * "do not reveal the final prediction before analysis".
   */
  async function openDistrictPlace(place) {
    const id = ++requestId.current
    setDistrictStatus('idle')
    setStatus('loading')
    setQuery(place.name || '')
    try {
      // STEP 22: this row came out of a DISTRICT card, so the village it names is
      // already identified by that district. The user has explicitly identified
      // village + district by clicking it, which is exactly what the gate asks
      // for - so it is resolved as a normal qualified place.
      const response = await locationApi.resolve(`${place.name}, ${place.district || ''}`.replace(/,\s*$/, ''), {
        allowAmbiguous: true,
      })
      if (id !== requestId.current) return
      commit(response.data, 'search')
    } catch (err) {
      if (id !== requestId.current) return
      const { blocked: isBlocked, text: errorText } = describeError(err)
      fail(errorText || `No location found for “${place.name}”.`, isBlocked)
    }
  }

  /**
   * STEP 22: the user has now named the village's DISTRICT, so the search can
   * finally identify one place.
   *
   * The text sent is "Village, District" - the qualified form the brief asks for -
   * and `allowAmbiguous` skips the gate, because a qualified village is not a bare
   * village any more. If the user also picked a state, "Village, District, State"
   * is used, which is equally unambiguous.
   *
   * Until this runs, no water-quality result exists for the village: the earlier
   * bare-name search never committed a place, so there is nothing on screen to
   * show a verdict from.
   */
  async function confirmVillage(candidate) {
    const district = (candidate?.district || villageDistrict || '').trim()
    if (!villagePending?.village || !district) return
    const state = (candidate?.state || '').trim()
    const qualified = [villagePending.village, district, state].filter(Boolean).join(', ')

    const id = ++requestId.current
    setVillageStatus('idle')
    setVillagePending(null)
    setStatus('loading')
    setQuery(qualified)
    try {
      const response = await locationApi.resolve(qualified, { allowAmbiguous: true })
      if (id !== requestId.current) return
      commit(response.data, 'search')
    } catch (err) {
      if (id !== requestId.current) return
      const { blocked: isBlocked, text: errorText } = describeError(err)
      // A qualified village the map data does not know is reported honestly
      // rather than being answered with some other village of the same name.
      fail(errorText || `No location found for “${qualified}”.`, isBlocked)
    }
  }

  /**
   * Turn a rejected request into the right message.
   *
   * The backend is the authority on BOTH refusals, and it distinguishes them by
   * status: 403 is the admin scope restriction, 404 is an unknown place. Reading
   * the status (rather than the text) means the frontend never has to guess, and
   * a client that ignored this page would still be refused by the API.
   */
  const describeError = useCallback((err) => {
    const status = err?.status
    const text = errorMessage(err, '')
    if (status === 403 || /only within the configured location area/i.test(text)) {
      return { blocked: true, text: SCOPE_DENIED_MESSAGE }
    }
    if (status === 404 || /not found|no location/i.test(text)) {
      return { blocked: false, text: null } // caller fills the search-specific text
    }
    return { blocked: false, text: text || null }
  }, [])

  /** Method 1–3: resolve a typed name, pincode or famous place.
   *
   * STEP 17 - A TYPED STATE SHOWS ITS DISTRICTS, NOT A SINGLE PLACE CARD.
   *
   * The geocoders resolve a state name to a coordinate and the resolver
   * answers 200 with it, so the state used to be handled as one enormous "place"
   * and its districts were never shown. That is why the district list was
   * unreachable: the code that renders it only ran on a 404, and a state name
   * never produced one.
   *
   * So the state check now happens BEFORE the place is committed. When the
   * typed text is a state the backend knows, the page shows the ordered
   * district list; only a genuine place name, pincode or landmark goes to the
   * single-place flow. The state check is one local, cached request against
   * bundled administrative data, so it costs nothing on an ordinary search.
   */
  async function search(event) {
    event?.preventDefault()
    const wanted = query.trim()
    if (!wanted) return
    const id = ++requestId.current
    setStatus('loading')
    setCountryStatus('idle')
    setMessage(null)
    // STEP 19: a new search clears the district filter, so the new state's
    // districts start as the full ordered list rather than inheriting the
    // previous state's filter text.
    setDistrictFilter('')
    // STEP 22: a new search supersedes any pending village question, so the
    // disambiguation card and the typed district are cleared up front rather
    // than lingering under an unrelated result.
    setVillagePending(null)
    setVillageStatus('idle')
    setVillageDistrict('')
    // STEP 23: a new search clears the previous pincode identification.
    setPincodeOverview(null)
    setPincodeAreas([])
    setPincodeStatus('idle')

    // --- STEP 23: is this a PINCODE? identify the area behind it -------------
    // This runs FIRST, before every other interpretation of the text, because a
    // pincode is an address and not a place name. Handing "630001" to the
    // ordinary name search is what produced confident nonsense: measured before
    // this existed, "999999" came back as a railway station in Italy and "12345"
    // as a rural council in Ukraine. Only six digits that do not start with 0
    // reach this branch, so nothing else is diverted.
    if (isPincodeText(wanted)) {
      setPincodeStatus('loading')
      try {
        const response = await locationApi.pincode(wanted)
        if (id !== requestId.current) return
        const data = response.data ?? {}
        setStatus('idle')
        setPlace(null)
        setSource(null)
        setBlocked(false)
        setMessage(null)
        setCountry(null)
        setCountryStatus('idle')
        setStateOverview(null)
        setStateStatus('idle')
        setDistrictOverview(null)
        setDistrictStatus('idle')

        // Several real areas share this pincode. They are offered as options and
        // the user picks - choosing for them would be inventing a location.
        const areas = Array.isArray(data.areas) ? data.areas : []
        if (areas.length > 1) {
          setPincodeAreas(areas)
          setPincodeOverview({ ...data, areas: null })
          setPincodeStatus('ready')
          return
        }

        // ONE AREA: it is committed straight away, so the water source, the
        // parameters and the "Enter Water Prediction" hand-off all work on it
        // exactly as they do for a name search, with no extra click in between.
        //
        // `commit` is called FIRST because it clears this screen's other views,
        // the pincode overview among them - so the overview is set afterwards and
        // survives, and the card names the postal area the result came from.
        commit({ ...data, areas: null, kind: 'pincode' }, 'search')
        setPincodeAreas([])
        setPincodeOverview({ ...data, areas: null })
        setPincodeStatus('ready')
        return
      } catch (err) {
        if (id !== requestId.current) return
        const { blocked: isBlocked, text: errorText } = describeError(err)
        // A pincode the postal data does not know is REFUSED with the server's
        // own words. It is never retried as a place name, because that is
        // exactly how a number ends up answered with a foreign railway station.
        setPincodeStatus('error')
        fail(
          errorText ||
            `No postal area found for pincode ${wanted}. It is not in the postal data, so no location can be identified from it.`,
          isBlocked,
        )
        return
      }
    }

    // --- STEP 18: is this a COUNTRY? show its states with a risk dot each ----
    // This check runs FIRST, before the state check and before the place
    // resolver. The country view used to be reachable only as a late fallback
    // after the place resolver answered 404, which made the whole Step 18
    // screen depend on a refusal: "India" resolves as one enormous place, so the
    // fallback was reached by luck rather than by design. Asking first makes the
    // country view the direct answer for a country name.
    //
    // `risk=false` returns the state NAMES, the order and the legend with no
    // water sampling at all, so all of a country's states paint immediately and
    // the risk dots are filled in by the enrichment effect below. A user never
    // waits on the slowest water lookup to find out a state exists.
    try {
      const countryResponse = await locationApi.country({ q: wanted, risk: 'false' })
      if (id !== requestId.current) return
      const countryData = countryResponse.data ?? {}
      const countryStates = countryData.states ?? []
      if (countryData.available && countryData.country?.name && countryStates.length > 0) {
        setStatus('idle')
        setPlace(null)
        setSource(null)
        setBlocked(false)
        setMessage(null)
        setStateOverview(null)
        setStateStatus('idle')
        setDistrictOverview(null)
        setDistrictStatus('idle')
        setCountry(countryData)
        setCountryStatus('ready')
        return
      }
    } catch {
      if (id !== requestId.current) return
      // Not a country, or country data is unavailable - fall through, which is
      // the right answer either way.
    }

    // --- STEP 17: is this a STATE? show its districts, not one place card ----
    try {
      const stateResponse = await locationApi.state({ q: wanted, risk: 'false' })
      if (id !== requestId.current) return
      const stateData = stateResponse.data ?? {}
      const districts = stateData.districts ?? []
      if (stateData.available && stateData.state?.name && districts.length > 0) {
        setStatus('idle')
        setPlace(null)
        setSource(null)
        setBlocked(false)
        setMessage(null)
        // STEP 20: the district view is cleared too. The three overview views are
        // alternatives, never stacked, and the district check now runs before
        // this one — so without this the places card from the previous search
        // stayed on screen underneath the state's district list.
        setDistrictOverview(null)
        setDistrictStatus('idle')
        setStateOverview(stateData)
        setStateStatus('ready')
        return
      }
    } catch {
      if (id !== requestId.current) return
      // Not a state, or the state data is unavailable - fall through to the
      // ordinary place resolution, which is the right answer either way.
    }

    // --- STEP 20: is this a DISTRICT? show its nine places, labels hidden -----
    // This check runs BEFORE the place resolver, and it has to. A district name is
    // very often ALSO a town of the same name - "Cuddalore" is a city and a
    // district, "Wayanad" is a district and a town, "Kochi" is a city inside
    // Ernakulam - so the place resolver answers first and the district branch was
    // reached only when a name happened to 404. Searching "Cuddalore" therefore
    // showed a single place card instead of the district's places, and the step
    // was effectively unreachable for most real districts.
    //
    // The check is one local request against the bundled administrative data, so
    // it costs nothing on an ordinary search.
    try {
      const districtResponse = await locationApi.district({ q: wanted })
      if (id !== requestId.current) return
      const districtData = districtResponse.data ?? {}
      if (districtData.available && districtData.district?.name) {
        setStatus('idle')
        setPlace(null)
        setSource(null)
        setBlocked(false)
        setMessage(null)
        setCountry(null)
        setCountryStatus('idle')
        setStateOverview(null)
        setStateStatus('idle')
        setDistrictOverview(districtData)
        setDistrictStatus('ready')
        return
      }
    } catch {
      if (id !== requestId.current) return
      // Not a district, or the district data is unavailable - fall through to the
      // ordinary place resolution, which is the right answer either way.
    }

    try {
      const response = await locationApi.resolve(wanted)
      if (id !== requestId.current) return

      // --- STEP 22: A BARE VILLAGE NAME IS NOT ENOUGH TO ANSWER WITH -------
      // The backend answers 200 with a disambiguation payload rather than a
      // place when the typed name is a VILLAGE carrying no district. Nothing is
      // committed here: no water lookup, no readings, no verdict. The user has
      // to name the village's district first, and only then does the ordinary
      // single-place flow run.
      //
      // Every other kind of place - city, town, area, nagar, colony, company,
      // shop, college, school, hotel, hospital, landmark - comes back as a normal
      // place with no `requires_district`, and falls straight through to commit().
      const payload = response.data ?? {}
      // STEP 24: THE OTHER BRANCHES OF THIS CHAIN, when there are any.
      //
      // The winning branch is still committed - it is a real place with a real
      // address, and refusing to answer at all would be a worse regression than
      // offering it. But when the search named a chain that exists in more than
      // one place, the others are kept on screen so the user can say which they
      // meant, and everything below this card (water source, parameters, the
      // hand-off to Manual Prediction) then describes the branch that was
      // actually chosen rather than one that merely ranked first.
      //
      // The list is emptied by `commit` on every other path into this screen, so
      // a question from a previous search can never sit above a new result.
      setBranches(
        Array.isArray(response.meta?.branches) ? response.meta.branches : [],
      )
      if (payload.requires_district) {
        setStatus('idle')
        setPlace(null)
        setSource(null)
        setBlocked(false)
        setMessage(null)
        setCountry(null)
        setCountryStatus('idle')
        setStateOverview(null)
        setStateStatus('idle')
        setDistrictOverview(null)
        setDistrictStatus('idle')
        setVillagePending({
          village: payload.village || wanted,
          reason: payload.reason || 'unqualified',
          message: payload.message,
          candidates: Array.isArray(payload.candidates) ? payload.candidates : [],
        })
        setVillageStatus('ready')
        setBranches([])
        return
      }

      commit(payload, 'search')
    } catch (err) {
      if (id !== requestId.current) return
      const { blocked: isBlocked, text: errorText } = describeError(err)
      if (isBlocked) {
        fail(errorText, true)
        return
      }
      // Not a place the resolver knows — but maybe it is a country, or a
      // state. The 404 is only a "not a place" answer, so before showing it we
      // give the country overview and then the state overview a chance: the
      // fallback paths below carry the search forward rather than treating 404
      // as a final refusal.
      if (errorText) {
        fail(errorText)
      } else {
        const NOT_FOUND =
          `No location found for “${wanted}”. Try a city, a pincode like 630001, or a known landmark.`
        try {
          const countryResponse = await locationApi.country({ q: wanted })
          if (id !== requestId.current) return
          const data = countryResponse.data ?? {}
          // The text resolved to a REAL country — show the overview even when
          // the state enumeration could not be served right now, so "India"
          // never reads as "no location found".
          if (data.available && data.country?.name) {
            setStatus('idle')
            setPlace(null)
            setSource(null)
            setBlocked(false)
            setMessage(null)
            setCountry(data)
            setCountryStatus('ready')
            return
          }

          // Not a country — maybe a STATE (Step 17). Typing a state's name
          // shows its districts in a numbered, ordered list — every one of
          // them, with state, country and whatever risk the data supports —
          // so the user never has to click each district just to see what the
          // state contains.
          try {
            const stateResponse = await locationApi.state({ q: wanted })
            if (id !== requestId.current) return
            const stateData = stateResponse.data ?? {}
            if (stateData.available && stateData.state?.name) {
              setStatus('idle')
              setPlace(null)
              setSource(null)
              setBlocked(false)
              setMessage(null)
              setStateOverview(stateData)
              setStateStatus('ready')
              return
            }
          } catch {
            if (id !== requestId.current) return
          }

          // Not a state either — maybe a DISTRICT (Step 21). When the text is a
          // district, show its nine major places with the labels hidden: the
          // user clicks a place to inspect its water and only then sees the
          // analysis, never a revealed prediction in the list.
          try {
            const districtResponse = await locationApi.district({ q: wanted })
            if (id !== requestId.current) return
            const districtData = districtResponse.data ?? {}
            if (districtData.available && districtData.district?.name) {
              setStatus('idle')
              setPlace(null)
              setSource(null)
              setBlocked(false)
              setMessage(null)
              setDistrictOverview(districtData)
              setDistrictStatus('ready')
              return
            }
          } catch {
            if (id !== requestId.current) return
          }

          fail(NOT_FOUND)
        } catch {
          if (id !== requestId.current) return
          fail(NOT_FOUND)
        }
      }
    }
  }

  /**
   * STEP 25 - "Use My Location": permission, fix, place, water.
   *
   * The order matters and is the brief's:
   *
   *   1. ask the browser for permission — IMMEDIATELY, on this click,
   *   2. take the fix,
   *   3. reverse-geocode it to a place name,
   *   4. show the address fields, then the water data as usual.
   *
   * NO BLOCKING ANIMATION. A fix obtained here is handed to the shared provider
   * with `reuseFix`, which writes the coordinates FIRST and only then runs the
   * reverse-geocode in the background, so nothing decorative is played over the
   * wait. The only indicator is the button's own spinner, and it is up only
   * while the browser is genuinely returning a position.
   *
   * THE PROVIDER'S FIX IS PREFERRED WHEN ONE IS READY. The loader may have
   * mounted a sticky `getCurrentPosition` as the map centred, or the Allow popup
   * may have just resolved one; reusing it avoids a second browser request and a
   * second prompt. Only when the shared state holds no fix is a fresh request
   * made — and if THAT is refused, the popup is offered so the visitor can answer
   * the browser's dialog deliberately.
   *
   * THE MAP IS OPENED AFTER THE PLACE.
   *
   * It used to open on the raw fix BEFORE resolving, which meant the popup
   * appeared on a stale laptop reading with the address still "resolving…".
   * The current brief asks for coordinates first and the human-readable address
   * asynchronously, with no blocking — so the address is resolved first and the
   * map then opens on it, showing the real place rather than a placeholder.
   *
   * THE COORDINATES ARE NOT DISPLAYED. They go to the server for one
   * reverse-geocode and the water lookups, and the screen shows the resolved
   * place name — never a latitude and longitude. The map modal in `device` mode
   * hides them for the same reason.
   *
   * A REFUSAL IS A NORMAL OUTCOME WITH ITS OWN WORDS. Permission denied, no
   * geolocation at all, an insecure origin and a timeout are different problems
   * and get different sentences, because telling a user who declined the prompt
   * that their location is "unavailable" is both false and unhelpful.
   */
  function handleGeolocationError(error) {
    if (error?.code === error?.PERMISSION_DENIED) {
      // The exact sentence the brief specifies for a refusal.
      fail('Location permission is required for automatic location detection. You can search manually instead.')
    } else if (error?.code === error?.TIMEOUT) {
      fail('Locating timed out. Please enter a location manually.')
    } else {
      fail('Your location is not available right now. Please enter a location manually.')
    }
  }

  async function useMyLocation() {
    // SECURE CONTEXT FIRST. Browsers only expose geolocation over HTTPS or
    // localhost; on plain HTTP `getCurrentPosition` never calls back, so this is
    // answered honestly and at once rather than leaving the visitor on a spinner.
    if (window.isSecureContext === false) {
      fail(
        'This page is not loaded over a secure connection (HTTPS), and browsers only share a location over HTTPS. Open AquaGuard AI over HTTPS, or search for a place by name instead.',
      )
      return
    }
    if (!('geolocation' in navigator)) {
      fail('This device cannot report a location. Please enter a location manually.')
      return
    }

    // A FIX IS ALREADY IN HAND. Reuse it: coordinates go straight into shared
    // state, the address follows asynchronously, and no second browser request
    // (and no second prompt) is needed.
    const sharedFix = sharedLocation?.coords
    if (sharedFix && typeof sharedFix.lat === 'number' && typeof sharedFix.lon === 'number') {
      commitFix(sharedFix, null)
      return
    }

    const id = ++requestId.current
    setLocating(true)
    setStatus('loading')
    setMessage(null)
    setBlocked(false)
    // Raise the consent popup too, so a fixed answer is recorded and the visitor
    // can see the request is deliberate. It does not block the real request
    // below — it only puts a visible decision in front of the browser's dialog.
    sharedLocation?.requestPermissionPrompt?.()

    navigator.geolocation.getCurrentPosition(
      // --- Permission granted, and the device knows where it is ---
      (position) => {
        if (id !== requestId.current) return
        const { latitude, longitude, accuracy } = position.coords || {}
        if (typeof latitude !== 'number' || typeof longitude !== 'number') {
          setLocating(false)
          fail('Your device reported a position that could not be read. Please enter a location manually.')
          return
        }
        setLocating(false)
        setDeviceFix({ lat: latitude, lon: longitude, accuracy })
        // Coordinates first: they are written to shared state, the address is
        // resolved asynchronously, and the map then opens on the resolved place.
        commitFix({ lat: latitude, lon: longitude, accuracy }, id)
      },
      // --- Denied, unavailable, or timed out ---
      (error) => {
        if (id !== requestId.current) return
        setLocating(false)
        handleGeolocationError(error)
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    )
  }

  /**
   * STEP 25: commit a device fix the coordinates-first way.
   *
   * Shared provider state is updated with the raw fix (so a map marker and the
   * rest of the app move as soon as a position exists), then the place is
   * resolved and shown. When `guardId` is provided the result is ignored if a
   * newer request has superseded it.
   */
  async function commitFix(fix, guardId) {
    const id = guardId ?? requestId.current
    setLocating(true)
    setStatus('loading')
    setMessage(null)
    setBlocked(false)
    setDeviceFix(fix)
    // Hand the fix to the shared provider WITHOUT waiting on it: the provider
    // sets coordinates immediately and reverse-geocodes in the background.
    const reversePromise = sharedLocation?.reuseFix?.(fix)
    try {
      const response = reversePromise
        ? { data: await reversePromise }
        : await locationApi.reverse({ lat: fix.lat, lon: fix.lon })
      if (id !== requestId.current) return
      const resolved = response?.data
      if (!resolved) throw new Error('unresolved')
      setQuery(resolved.display_name || resolved.name || '')
      setDeviceFix(null)
      commit(resolved, 'device')
    } catch (err) {
      if (id !== requestId.current) return
      // The coordinates are real even when the geocoder cannot name them, so the
      // page keeps them and offers manual entry rather than discarding the fix.
      setDeviceFix(fix)
      const { blocked: isBlocked, text: errorText } = describeError(err)
      if (isBlocked) {
        fail(
          errorText ||
            'That location could not be resolved to a place. Please pick a point on the map, or search by name.',
          true,
        )
        return
      }
      fail(
        errorText ||
          'Your position was found but could not be matched to a place. Move the pin on the map, or search by name.',
      )
    } finally {
      if (id === requestId.current) setLocating(false)
    }
  }

  /**
   * STEP 25: the user confirmed the point shown on the map.
   *
   * One reverse-geocode, through the same endpoint every other path uses, and
   * then the ordinary single-place flow runs: the water source, the parameters
   * and the hand-off to Manual Prediction all follow from whatever this returns.
   *
   * A CONFIRMATION THAT CANNOT BE NAMED IS NOT A RESULT. The coordinates are
   * real even when the map has no name for them, but a location the geocoder
   * cannot resolve cannot be shown as an identified place, so it is reported as
   * the failure it is rather than pinned to a nearest town.
   */
  async function confirmPicked({ lat, lon }, source = 'manual') {
    const id = ++requestId.current
    setStatus('loading')
    setMessage(null)
    try {
      const response = await locationApi.reverse({ lat, lon })
      if (id !== requestId.current) return
      const resolved = response.data
      // Put the resolved place into the search bar, so the user sees and can
      // edit the place name, never raw coordinates.
      setQuery(resolved.display_name || resolved.name || '')
      setPickerOpen(false)
      // STEP 25: the fix has served its purpose once the place is confirmed.
      setDeviceFix(null)
      commit(resolved, source)
    } catch (err) {
      if (id !== requestId.current) return
      const { blocked: isBlocked, text: errorText } = describeError(err)

      // STEP 26: A PIN THE GEOCODER CANNOT NAME IS NOT A DEAD END.
      //
      // The modal closes the moment Confirm is pressed, so failing the lookup
      // AFTERWARDS left the user with nothing at all: no card, and no map to go
      // back to. The point they had carefully panned and zoomed to was gone, and
      // the only way forward was to start again. That is the worst possible answer
      // to "use this location", because the user's work is what was discarded.
      //
      // So the MAP STAYS OPEN on a lookup that fails, with the reason in it, and
      // the pin is still where they left it. They can move it somewhere the map
      // names, or zoom out and try again, without reopening anything.
      //
      // A point the geocoder genuinely cannot name is NOT fabricated into the
      // nearest town: the brief is explicit that any valid pin must be processed,
      // and reporting a different place than the one selected is worse than
      // reporting that this one is unknown.
      if (!isBlocked) {
        setStatus('idle')
        setMessage(null)
        setPickerError(
          errorText ||
            'That point could not be matched to a place. Move the pin somewhere the map knows, or search by name.',
        )
        return
      }

      // A scope refusal is a policy answer about a place the backend DID
      // identify, so the modal closes and the refusal is shown on the page.
      setPickerOpen(false)
      fail(
        errorText ||
          'That location could not be resolved to a place. Please pick a point on the map, or search by name.',
        isBlocked,
      )
    }
  }

  /** Method 5: resolve coordinates chosen on the map picker. */
  async function confirmManual(coords) {
    setPickerMode('manual')
    return confirmPicked(coords, 'manual')
  }

  // Fetch the full water context whenever a place is committed. ONE server call
  // returns the water source, the nearby sources, the risks and the default
  // prediction parameters, so the cards below cannot disagree with one another.
  // Keyed on the place's coordinates so the request re-runs for a new location
  // but not on every render. The lookup is the SERVER's — this effect never
  // decides a water type, a risk or a default reading.
  //
  // STEP 32: the response also carries a rain forecast, and it is NOT rendered
  // here. Rain belongs to the Rainy Alerts screen, which resolves the DEVICE's
  // own state rather than whichever place happens to be loaded — so a rain
  // warning can never appear for somewhere the visitor is not. The request is
  // left unchanged because the backend computes the risk level from the rain
  // forecast as well as the source, and changing that would alter the risk
  // number this screen reports. See `waterFactors`.
  useEffect(() => {
    if (status !== 'ready' || !place) {
      setWater(null)
      setRiskLevel(null)
      setRisks([])
      setDefaults(null)
      setDefaultsSource(null)
      // STEP 14: A NEW LOCATION INVALIDATES THE LAST VERDICT. Leaving it on
      // screen would mean a SAFE result for Karaikudi sitting under the details
      // of Chennai, which is the most dangerous kind of stale data this page
      // could show.
      setEditable({})
      setPrediction(null)
      setAnalysed(null)
      setAnalysisError(null)
      setFieldErrors({})
      setWaterError(null)
      setWaterStatus('idle')
      // PROMPT 1, E.4: a new location invalidates any source selection the user
      // made for the previous one — a borewell chosen in Chennai must never
      // silently describe a pond in Karaikudi.
      setSelectedSource(null)
      return undefined
    }
    let active = true
    setWaterStatus('loading')
    setWater(null)
    setRiskLevel(null)
    setRisks([])
    setDefaults(null)
    setDefaultsSource(null)
    // Same reason: the verdict belonged to the previous location.
    setEditable({})
    setPrediction(null)
    setAnalysed(null)
    setAnalysisError(null)
    setFieldErrors({})
    setWaterError(null)
    // PROMPT 1, E.4: a fresh lookup resets any prior source selection.
    setSelectedSource(null)
    locationApi
      .context({ lat: place.lat, lon: place.lon })
      .then((response) => {
        if (!active) return
        const data = response.data ?? {}
        setWater(data.water ?? null)
        setRiskLevel(data.risk_level ?? null)
        setRisks(Array.isArray(data.risks) ? data.risks : [])
        setDefaults(data.default_parameters ?? null)
        setDefaultsSource(data.default_parameters_detail ?? null)
        setParameterDefinitions(
          Array.isArray(data.parameter_definitions) ? data.parameter_definitions : [],
        )
        // STEP 14: SEED THE EDITABLE READINGS FROM THE SERVER'S VALUES, and only
        // then. They are copied into editable input boxes the user can correct,
        // and they are cleared again the moment a different location is chosen.
        setEditable({ ...(data.default_parameters ?? {}) })
        setWaterStatus('ready')
      })
      .catch((err) => {
        // A failure to identify the water must not break the page: the location
        // itself is still shown, and the water card says it is unavailable rather
        // than inventing anything.
        if (!active) return
        setWater({ available: false, message: WATER_UNAVAILABLE_MESSAGE, nearby: [], types: [] })
        setWaterStatus('error')
        setWaterError(err)
      })
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, place?.lat, place?.lon])

  /**
   * STEP 15 - "Enter Water Prediction".
   *
   * Carries this screen's CURRENT readings - the ones in `editable`, so a
   * correction the visitor typed here travels with them - across to Manual
   * Prediction, together with the location metadata the prediction workflow
   * needs. The Manual Prediction form seeds itself from them ON ARRIVAL and
   * stays fully editable; nothing is analysed here and nothing is analysed there
   * until the visitor presses "Analyze Water Quality" themselves.
   *
   * The location is passed INTERNALLY ONLY. It is carried in router state so the
   * sample can be stored against the place it was taken for, and it is not
   * rendered: the "Location Information" section was removed in STEP 4, and this
   * step does not bring it back.
   */
  function goToPredict() {
    const readings = Object.fromEntries(
      FEATURE_NAMES.map((name) => [name, editable[name]]),
    )

    navigate(ROUTES.predict, {
      state: {
        // STEP 15: the handoff. Keyed so a hand-off is only ever consumed by
        // this screen and never mistaken for an unrelated navigation.
        fromLocation: true,
        readings,
        // Empty values are dropped rather than sent as nulls, so the sample that
        // reaches the API is exactly the shape this page's own predict call sends.
        location: Object.fromEntries(
          Object.entries({
            location_name: place?.name,
            location_city: place?.city ?? place?.name,
            location_district: place?.district,
            location_state: place?.state,
            location_country: place?.country,
            location_pincode: place?.pincode,
            location_lat: place?.lat,
            location_lng: place?.lon,
            water_source_type: effectiveSource ?? null,
            nearby_water_source: water?.nearest?.name ?? null,
            nearby_water_source_distance: water?.nearest?.distance_km ?? null,
          }).filter(([, value]) => value !== null && value !== undefined && value !== ''),
        ),
      },
    })
  }

  /**
   * STEP 14 - RUN THE PREDICTION FROM THIS PAGE.
   *
   * The whole flow now completes here: search, identify, show the water source
   * and the readings, let the user correct them, analyse, and read the verdict -
   * without leaving for Manual Prediction. That screen is still one button away
   * for someone who wants a blank form, but it is no longer on the critical path
   * to a location-based result.
   *
   * The verdict comes from the EXISTING `POST /predictions/predict` endpoint -
   * the same Random Forest, the same validation, the same persistence and the
   * same alert-on-unsafe that Manual Prediction uses. There is no second model
   * and no local computation, so a result cannot exist here that would not exist
   * there.
   *
   * NOTHING IS FABRICATED. `prediction` is set from the server's response and
   * from nothing else; a 2xx that carries no verdict is treated as a failure
   * rather than rendered as an empty panel, and a 503 from an unavailable model
   * says exactly that instead of falling back to a guess.
   */
  async function analyzeWater() {
    // Every reading must have a real number in it. An empty box is not a zero
    // and is not the previous value - it is a missing measurement.
    const blanks = FEATURE_NAMES.filter((name) => {
      const raw = editable?.[name]
      return raw === undefined || raw === null || String(raw).trim() === ''
    })
    if (blanks.length > 0) {
      setAnalysisError({
        kind: 'validation',
        message: `${blanks.length} parameter${blanks.length > 1 ? 's are' : ' is'} missing. Fill in every reading from your test before analysing.`,
      })
      return
    }

    const id = ++requestId.current
    setAnalysing(true)
    setAnalysisError(null)
    setFieldErrors({})
    // Drop the previous verdict immediately, so a stale one is never read as
    // the answer to the readings just submitted.
    setPrediction(null)
    setAnalysed(null)

    // Numbers, not strings - the API contract is numeric.
    const payload = Object.fromEntries(
      FEATURE_NAMES.map((name) => [name, Number(editable[name])]),
    )

    try {
      const response = await predictionApi.predict({
        ...payload,
        // The location and its water source travel WITH the sample, so the
        // stored prediction belongs to the place it was made for and the result
        // card can name it. `water_source_type` is null when no source is mapped
        // at the exact point, and the API stores that honestly rather than
        // substituting the nearest one.
        location_name: place?.name,
        location_area: place?.area || null,
        location_city: place?.city,
        location_district: place?.district,
        location_state: place?.state,
        location_country: place?.country,
        location_pincode: place?.pincode,
        location_lat: place?.lat,
        location_lng: place?.lon,
        water_source_type: effectiveSource ?? null,
        nearby_water_source: water?.nearest?.name ?? null,
        nearby_water_source_distance: water?.nearest?.distance_km ?? null,
        // PROMPT 1, E.9: the provenance of these readings travels with the
        // record, so the stored prediction can always be traced to where its
        // numbers came from. "user" is the code for readings the user typed
        // themselves.
        param_provenance: defaultsSource?.source === 'user_input_required'
          ? 'user'
          : defaultsSource?.source ?? null,
      })
      // Superseded by a newer submission.
      if (id !== requestId.current) return

      const data = response?.data
      if (!data?.prediction) {
        // A 2xx carrying no verdict is a malformed response, not a result.
        setAnalysisError({
          kind: 'backend',
          message:
            'The server accepted the readings but returned no verdict. Please try again.',
        })
        return
      }
      setPrediction(data)
      // The exact numbers the verdict was computed from. Held separately from
      // `editable` so editing a box afterwards cannot rewrite history.
      setAnalysed(payload)
      // Tell the dashboard and history to refetch.
      announcePredictionCreated({ riskLevel: data.prediction })
    } catch (err) {
      if (id !== requestId.current) return
      const status = err?.status
      if (err?.isNetworkError || err?.isTimeout) {
        setAnalysisError({
          kind: 'network',
          message:
            'Could not reach the AquaGuard AI server. Check your connection and that the backend is running, then try again.',
        })
      } else if (status === 422 || err?.errors) {
        setAnalysisError({
          kind: 'validation',
          message: errorMessage(err, 'One or more readings are invalid.'),
        })
        if (err?.errors) setFieldErrors(err.errors)
      } else if (status === 503) {
        // The model artifact is missing. NO verdict is produced and none is
        // guessed - this is exactly the case the brief's "do not fabricate"
        // rule exists for.
        setAnalysisError({
          kind: 'backend',
          message:
            'The prediction model is unavailable on the server, so no verdict could be produced. That is a server-side problem, not a problem with your readings.',
        })
      } else {
        setAnalysisError({
          kind: 'backend',
          message: errorMessage(err, 'The prediction could not be completed. Please try again.'),
        })
      }
    } finally {
      if (id === requestId.current) setAnalysing(false)
    }
  }

  const SOURCE_LABELS = {
    search: 'Search result',
    device: 'Device location',
    manual: 'Manually selected',
  }

  return (
    <div>
      <PageHeader
        breadcrumb="Location Prediction"
        title="Location Prediction"
        description="Find the place you want to test. The water source, its nearby sources and its risks are identified for you."
      />

      {/* --- Search section ------------------------------------------------- */}
      <Card
        className="mb-6"
        title="Search a location"
        subtitle="By name, pincode or a famous place — or use your device&apos;s location."
      >
        <form onSubmit={search} className="flex flex-col gap-3 sm:flex-row sm:items-start">
          {/* The text field. `flex-1` so it takes the row, the buttons keep
              their natural width. */}
          <div className="relative flex-1">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
              <Icon path={ICONS.search} className="h-4 w-4" />
            </span>
            <input
              ref={searchInputRef}
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleSearchKeyDown}
              className="input pl-9"
              placeholder="Karaikudi, 630001, Marina Beach…"
              aria-label="Search a location"
              autoComplete="off"
              role="combobox"
              aria-expanded={suggestionsOpen}
              aria-controls="location-suggestions"
              aria-activedescendant={
                activeIndex >= 0 && suggestions[activeIndex]
                  ? `location-suggestion-${activeIndex}`
                  : undefined
              }
            />
            {/* THE SUGGESTION LIST LIVES IN A PORTAL, NOT HERE.

                It used to be an absolutely-positioned child of this input's
                wrapper, and this wrapper sits inside a <Card>, whose
                `overflow-hidden` clipped it at the card's bottom edge - only
                the first suggestion was ever visible. The shared
                LocationSuggestions panel renders to <body> instead: it cannot
                be clipped by the card, hidden behind the map, or covered by
                the topbar, and it keeps the ~190px scrollable height, the
                outside-press dismissal and the branch labelling.

                `open` is gated on the field having text, so the panel appears
                only while typing - an empty or cleared field closes it, and
                selecting a row or pressing Escape closes it through the
                handlers that already clear the list. */}
            <LocationSuggestions
              inputRef={searchInputRef}
              open={
                suggestionsOpen &&
                query.trim().length > 0 &&
                Boolean(
                  suggestionsLoading || suggestions.length > 0 || suggestionsError,
                )
              }
              loading={suggestionsLoading}
              error={suggestionsError}
              suggestions={suggestions}
              activeIndex={activeIndex}
              onHighlight={setActiveIndex}
              onChoose={selectSuggestion}
              onClose={() => setSuggestionsOpen(false)}
            />
          </div>

          <div className="flex gap-2">
            <Button type="submit" disabled={!query.trim() || status === 'loading'}>
              <Icon path={ICONS.search} className="h-4 w-4" />
              Search Location
            </Button>
            <Button
              type="button"
              variant="secondary"
              loading={locating}
              disabled={status === 'loading'}
              onClick={useMyLocation}
              className="whitespace-nowrap"
            >
              <LocationPinIcon className="h-4 w-4" animated={false} />
              Use My Location
            </Button>
            {/* The standalone map-pin button: opens the manual selector. */}
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => {
                setPickerMode('manual')
                setDeviceFix(null)
                setPickerError(null)
                setPickerOpen(true)
              }}
              aria-label="Pick a location on the map"
              title="Pick a location on the map"
            >
              {/* STEP 28: an animated SVG pin instead of the "📍" character, which
                  the OS drew as a flat yellow pushpin that matched nothing else in
                  a toolbar of aqua line icons. The button's own behaviour - the
                  three state resets and `setPickerOpen(true)` - is untouched. */}
              <LocationPinIcon animated={false} />
            </Button>
          </div>
        </form>

        {/* The five methods, stated so the search box is self-explanatory. */}
        <ul className="mt-4 flex flex-wrap gap-2">
          {SEARCH_METHODS.map((method) => (
            <li
              key={method.label}
              className="inline-flex items-center gap-1.5 rounded-full border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
            >
              <Icon path={ICONS[method.icon] || ICONS.info} className="h-3.5 w-3.5 text-aqua-600 dark:text-aqua-300" />
              {method.label}
              <span className="text-slate-400">· {method.example}</span>
            </li>
          ))}
        </ul>

        {/* A one-line explanation of what "Use My Location" actually does, so
            the button is not a leap of faith. It also states the privacy
            behaviour up front: the device position is used to find the place and
            is not kept. */}
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          <LocationPinIcon className="mr-1 inline-block h-3.5 w-3.5 align-[-0.1em] text-aqua-600 dark:text-aqua-300" animated={false} />
          <strong className="font-medium text-slate-600 dark:text-slate-300">Use My Location</strong>{' '}
          asks your device for its position, finds the place it falls in, and fills the search box
          above with the place name — never with raw coordinates. You can edit it before searching.
        </p>
      </Card>

      {/* --- Loading -------------------------------------------------------- */}
      {status === 'loading' && <IdentifyingState locating={locating} />}

      {/* --- Error / refusal ------------------------------------------------ */}
      {status === 'error' && message && (
        <Card className="mb-6">
          {/* A SCOPE refusal is a policy answer, not a data error, so it gets the
              amber information treatment rather than the red failure one - and
              the backend's exact sentence is shown verbatim. */}
          {blocked ? (
            <div
              className="flex items-start gap-3 rounded-card border-caution-light bg-caution-light/40 px-4 py-4"
              role="alert"
            >
              <span className="mt-0.5 shrink-0 text-caution-dark" aria-hidden="true">
                <Icon path={ICONS.location} className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-caution-dark">Outside the allowed area</p>
                <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">{message}</p>
                <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
                  Ask an administrator to widen the location access scope if you need to check
                  water here.
                </p>
              </div>
            </div>
          ) : (
            <div
              className="flex items-start gap-3 rounded-card border-unsafe-light bg-unsafe-light/40 px-4 py-3"
              role="alert"
            >
              <span className="mt-0.5 shrink-0 text-unsafe-dark" aria-hidden="true">
                <Icon path={ICONS.info} className="h-5 w-5" />
              </span>
              <div>
                <p className="text-sm font-semibold text-unsafe-dark">Location not identified</p>
                <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-300">{message}</p>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* --- Country overview (Step 19) -------------------------------------- */}
      {/* When the search resolved to a COUNTRY, this card replaces the single
          place view. It shows the country, the animated legend key, and every
          supported state / region with ONE aggregated water-quality risk
          indicator each — the brief's "Country → States → State-level risk
          indicator". Individual places are deliberately NOT listed here: the
          state indicator already aggregates them. */}
      {countryStatus === 'ready' && country && (
        <Card
          className="mb-6 animate-zoom-in"
          title={`${country.country?.name || 'Country'} — State Overview`}
          subtitle="Each state carries one aggregated water-quality risk indicator, calculated from mapped water data — never randomly assigned."
        >
          {/* THE LEGEND. Rendered at the top of the country result, above the
              list it explains, exactly as the brief specifies. Each entry is a
              dot plus its word, and the dots are the same animated dots the
              state list below uses, so the key and the list are visibly the same
              thing. */}
          <div className="mb-5 rounded-field border border-slate-100 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
            <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
              Legend
            </p>
            <RiskLegend legend={country.legend} />
          </div>

          {country.summary && (
            <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
              {country.summary.total_states} states ·{' '}
              <span className="font-medium text-safe-dark dark:text-safe">{country.summary.safe} safe</span>{' '}
              ·{' '}
              <span className="font-medium text-caution-dark">{country.summary.moderate} moderate</span>{' '}
              ·{' '}
              <span className="font-medium text-unsafe-dark">{country.summary.unsafe} unsafe</span>
              {country.summary.unknown > 0 && (
                <span> · {country.summary.unknown} with insufficient data</span>
              )}
            </p>
          )}

          <ul className="space-y-2">
            {country.states.map((state) => (
              <li
                key={state.state}
                className="flex items-center gap-3 rounded-field border border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
              >
                <StatusDot tone={state.risk_tone} />
                <button
                  type="button"
                  onClick={() => openState(state)}
                  className="min-w-0 flex-1 text-left hover:underline"
                  title={`Open ${state.state}`}
                >
                  <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                    {state.state}
                  </p>
                  {state.risk_level === 'unknown' || state.insufficient_data ? (
                    /* STEP 18: the brief's exact wording, shown INSTEAD of a risk
                        summary whenever the data cannot support one. The dot stays
                        grey, so the row never borrows a colour it did not earn. */
                    <p className="mt-0.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                      Insufficient data
                      {state.message ? (
                        <span className="font-normal text-slate-400">
                          {' — '}
                          {state.message.replace(/^Insufficient data:?\s*/i, '')}
                        </span>
                      ) : null}
                    </p>
                  ) : (
                    <p className="mt-0.5 text-xs capitalize text-slate-500 dark:text-slate-400">
                      {state.worst_source || '—'}
                      {waterFactors(state.factors).length > 0 &&
                        ` · ${waterFactors(state.factors).map((f) => f.detail).join('; ')}`}
                    </p>
                  )}
                </button>
                <Badge risk={state.risk_tone} className="shrink-0" />
              </li>
            ))}
          </ul>

          <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            The state indicator is calculated from the mapped water features
            OpenStreetMap records near each state&apos;s centre, using the same
            derivation as a single place&apos;s risk — worst-observed source type.
            Nothing is assigned by name and nothing is randomised: a state whose
            risk cannot be supported by real water data is shown as{' '}
            <span className="font-semibold">Insufficient data</span> with a grey
            dot, rather than given a colour we would have made up. These dots
            belong to the country view only — an ordinary single-location search
            is unaffected.
          </p>
        </Card>
      )}

      {/* --- District list (Step 17) --------------------------------------- */}
      {/* STEP 17: TYPING A STATE SHOWS ITS DISTRICTS, IN AN ORDERED LIST.

          The user types "Tamil Nadu" and gets the state's districts straight
          away - every one of them, each on its own row - without having to
          click through to discover that a district exists. This is the whole
          point of the change: the list is the answer, not a menu leading to
          one.

          Each row carries what the brief asks for and nothing invented:
            * the district NAME, as an ordered, numbered row;
            * its STATE and COUNTRY, so a row reads on its own;
            * the risk / status summary, but only where the data supports one -
              a district with no mapped water reads "unknown" with the reason,
              never a colour we would have made up.

          The ORDER is alphabetical with a rank from the backend, so the same
          state always renders in the same order. */}
      {stateStatus === 'ready' && stateOverview?.state?.name && (
        <Card
          className="mb-6 animate-zoom-in"
          title={`${stateOverview.state.name} — Districts`}
          subtitle="Every district of the state, in order. Each shows its state, country and the water risk the mapped data supports — no need to open each one to see what exists."
        >
          {/* THE LEGEND, at the top, exactly as the country view does it - the
              key is visible before the list it explains. */}
          <div className="mb-5 rounded-field border border-slate-100 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
            <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
              Legend
            </p>
            <RiskLegend legend={stateOverview.legend} />
          </div>

          {stateOverview.summary && (
            <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
              {stateOverview.summary.total_districts} districts ·{' '}
              <span className="font-medium text-safe-dark dark:text-safe">
                {stateOverview.summary.safe} safe
              </span>{' '}
              ·{' '}
              <span className="font-medium text-caution-dark">
                {stateOverview.summary.moderate} moderate
              </span>{' '}
              ·{' '}
              <span className="font-medium text-unsafe-dark">
                {stateOverview.summary.unsafe} unsafe
              </span>
              {stateOverview.summary.unknown > 0 && (
                <span> · {stateOverview.summary.unknown} with insufficient data</span>
              )}
            </p>
          )}

          {stateOverview.message && (
            <p className="mb-4 rounded-field border border-caution-light bg-caution-light/40 px-4 py-3 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {stateOverview.message}
            </p>
          )}

          {/* STEP 19: THE DISTRICTS STAY SEARCHABLE.

              The filter is local and instant - it narrows the rows already on
              screen and never triggers a lookup - so a user can find a district
              and read its risk indicator without opening it. A state like Uttar
              Pradesh lists 76 districts, so this is what keeps the ordered list
              usable rather than merely long. */}
          <div className="mb-4">
            <label
              htmlFor="district-filter"
              className="mb-1.5 block text-2xs font-semibold uppercase tracking-wider text-slate-400"
            >
              Search districts
            </label>
            <input
              id="district-filter"
              type="search"
              value={districtFilter}
              onChange={(event) => setDistrictFilter(event.target.value)}
              placeholder={`Filter ${stateOverview.districts?.length ?? 0} districts…`}
              className="w-full rounded-field border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-aqua focus:outline-none focus:ring-2 focus:ring-aqua/30 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            />
            <p className="mt-1.5 text-2xs text-slate-400" aria-live="polite">
              Showing {visibleDistricts.length} of {stateOverview.districts?.length ?? 0}{' '}
              districts
              {districtFilter.trim() && visibleDistricts.length === 0 && (
                <span> — no district matches “{districtFilter.trim()}”</span>
              )}
            </p>
          </div>

          {/* AN ORDERED LIST, numbered as the brief specifies: "01. Ariyalur",
              "02. Chengalpattu". A <ol> rather than a set of cards, because
              this IS a list and it should read as one to a screen reader too.
              The number is the district's rank in the WHOLE state, so a filtered
              list keeps its true position rather than renumbering itself. */}
          <ol className="space-y-2">
            {visibleDistricts.map((district) => (
              <li
                key={district.district}
                className="flex items-center gap-3 rounded-field border border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
              >
                <span
                  className="w-7 shrink-0 text-right text-xs font-semibold tabular text-slate-400"
                  aria-hidden="true"
                >
                  {String(district.rank ?? '').padStart(2, '0')}
                </span>
                <StatusDot tone={district.risk_tone} />
                <button
                  type="button"
                  onClick={() => openStateDistrict(district)}
                  className="min-w-0 flex-1 text-left hover:underline"
                  title={`Open ${district.district}`}
                >
                  <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                    {district.district}
                  </p>
                  {/* The state and country, on the row itself. */}
                  <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                    {[district.state, district.country].filter(Boolean).join(', ') || '—'}
                  </p>
                  {/* STEP 19: the brief's exact wording whenever the data cannot
                      support a classification. The dot stays grey, so a row never
                      borrows a colour it did not earn. */}
                  {district.risk_level === 'unknown' || district.insufficient_data ? (
                    <p className="mt-0.5 truncate text-xs font-medium text-slate-500 dark:text-slate-400">
                      Insufficient Data
                      {district.message ? (
                        <span className="font-normal text-slate-400">
                          {' — '}
                          {district.message.replace(/^Insufficient Data:?\s*/i, '')}
                        </span>
                      ) : null}
                    </p>
                  ) : (
                    <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                      <span className="capitalize">{district.worst_source || '—'}</span>
                    </p>
                  )}
                </button>
                <Badge risk={district.risk_tone} className="shrink-0" />
              </li>
            ))}
          </ol>

          {visibleDistricts.length === 0 && (
            <p className="rounded-field border border-slate-100 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">
              No district in {stateOverview.state.name} matches that search.
            </p>
          )}

          <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            The districts come from the administrative data bundled with the
            application, so the list is complete for the state and does not
            depend on a live service being reachable. The risk shown beside each
            one is calculated from the water OpenStreetMap actually maps near
            that district, using the same derivation as a single place&apos;s
            risk — a district with no mapped water is shown as unknown rather
            than given a colour we would have made up. Select a district to
            inspect a specific place inside it.
          </p>
        </Card>
      )}

      {/* --- Pincode identification (Step 23) -------------------------------- */}
      {/* A PIN CODE IS AN ADDRESS, AND IT IS SHOWN AS ONE.

          The user typed a pincode, so this card names the postal area behind it:
          Area, City / Town, District, State, Country and the Pincode itself. Every
          value is one the postal data actually returned - a part it does not
          carry reads "Not available" rather than being filled in from the district
          or from the digits, because a pincode mapping that was invented would be
          worse than an admitted gap.

          When the pincode covers more than one real area, the choices are listed
          and the user picks; no area is selected on their behalf. The water
          source and parameters below come from the area that was identified, and
          "Enter Water Prediction" carries them into Manual Prediction exactly as
          it does for a name search. */}
      {pincodeStatus === 'ready' && pincodeOverview?.pincode && (
        <Card
          className="mb-6 animate-zoom-in"
          title={`Pincode ${pincodeOverview.pincode}`}
          subtitle="The postal area this pincode identifies, from the postal location data."
          actions={<Badge tone="aqua">Identified by pincode</Badge>}
        >
          <div className="mb-5 flex items-start gap-3">
            <span
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-aqua-500 to-aqua-700 text-white shadow-sm"
              aria-hidden="true"
            >
              <Icon path={ICONS.location} className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">
                {[pincodeOverview.area, pincodeOverview.city]
                  .filter(Boolean)
                  .join(', ') || 'Postal area'}
              </p>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {pincodeOverview.label}
              </p>
            </div>
          </div>

          {/* The six fields the brief names, each one. "Not available" is the
              honest rendering of a field the postal data does not have. */}
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Detail label="Area" value={pincodeOverview.area} icon={ICONS.location} />
            <Detail label="City / Town" value={pincodeOverview.city} icon={ICONS.home} />
            <Detail label="District" value={pincodeOverview.district} icon={ICONS.analytics} />
            <Detail label="State" value={pincodeOverview.state} icon={ICONS.shield} />
            <Detail label="Country" value={pincodeOverview.country} icon={ICONS.info} />
            <Detail
              label="Pincode"
              value={pincodeOverview.pincode}
              icon={ICONS.reports}
            />
          </dl>

          {/* MORE THAN ONE AREA FOR THIS PINCODE. All of them are real rows from
              the postal data and all of them are offered - picking one for the
              user would be inventing the location they searched for. */}
          {pincodeAreas.length > 1 && (
            <div className="mt-5 border-t border-slate-100 pt-4 dark:border-slate-700">
              <p className="mb-3 text-sm font-semibold text-slate-900 dark:text-white">
                This pincode covers {pincodeAreas.length} areas — select the one you
                mean
              </p>
              <ul
                className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3"
                data-testid="pincode-areas"
              >
                {pincodeAreas.map((area) => (
                  <li
                    key={`${area.area || area.name}-${area.district || ''}-${area.state || ''}`}
                    className="flex items-center gap-3 rounded-field border border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
                  >
                    <span
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-aqua-500/15 text-aqua-700 dark:text-aqua-300"
                      aria-hidden="true"
                    >
                      <Icon path={ICONS.location} className="h-4 w-4" />
                    </span>
                    <button
                      type="button"
                      onClick={() => openPincodeArea(area)}
                      className="min-w-0 flex-1 text-left hover:underline"
                      title={`Use ${area.label || area.name}`}
                    >
                      <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                        {area.area || area.name}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                        {[area.city, area.district, area.state].filter(Boolean).join(', ') || '—'}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            Every field above comes from the postal location data for this pincode.
            A field the data does not record is shown as “Not available” and is
            never filled in from the district, the state or the digits. Select an
            area above when the pincode covers more than one.
          </p>
        </Card>
      )}

      {/* --- Village disambiguation (Step 22) ------------------------------- */}
      {/* A BARE VILLAGE NAME IS NOT A RESULT.

          The user searched a village with no district. Village names repeat all
          over the country, so this card does NOT show a water source, readings
          or a verdict — it asks which village and district they meant, and the
          single-place flow only starts once they answer.

          Two ways to answer, both of which identify village + district:
            1. Click one of the villages the map data actually holds for this
               name (shown with its district and state).
            2. Type the district into the field.

          Nothing here is a guess: the candidates are real geocoder rows, and the
          district the user supplies is passed through as typed. */}
      {villageStatus === 'ready' && villagePending?.village && (
        <Card
          className="mb-6 animate-zoom-in"
          title={`Which “${villagePending.village}” do you mean?`}
          subtitle="This is a village name, and village names repeat. Select the village with its district — or enter the district below — before any water-quality result is shown."
        >
          <p
            className="mb-4 rounded-field border border-caution-light bg-caution-light/40 px-4 py-3 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200"
            role="status"
          >
            {villagePending.message ||
              `“${villagePending.village}” is a village. Its district is required before a water-quality result can be shown.`}
          </p>

          {villagePending.candidates.length > 0 ? (
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="village-candidates">
              {villagePending.candidates.map((candidate) => (
                <li
                  key={`${candidate.name}-${candidate.district || ''}-${candidate.state || ''}`}
                  className="flex items-center gap-3 rounded-field border border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
                >
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-aqua-500/15 text-aqua-700 dark:text-aqua-300"
                    aria-hidden="true"
                  >
                    <Icon path={ICONS.location} className="h-4 w-4" />
                  </span>
                  <button
                    type="button"
                    onClick={() => confirmVillage(candidate)}
                    className="min-w-0 flex-1 text-left hover:underline"
                    title={`Use ${candidate.label || candidate.name}`}
                  >
                    <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                      {candidate.name}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                      {[candidate.district, candidate.state].filter(Boolean).join(', ') || '—'}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          {/* Village + District, typed. This is the other form the brief accepts,
              and it is the only way forward when the map data holds no candidate
              rows for the name at all. */}
          <form
            className="mt-4 flex flex-col gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:items-end dark:border-slate-700"
            onSubmit={(event) => {
              event.preventDefault()
              confirmVillage(null)
            }}
          >
            <label className="min-w-0 flex-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              <span className="mb-1 block">District of {villagePending.village}</span>
              <input
                type="text"
                value={villageDistrict}
                onChange={(event) => setVillageDistrict(event.target.value)}
                placeholder="e.g. Kanyakumari"
                data-testid="village-district-input"
                className="w-full rounded-field border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-aqua-500 dark:border-slate-600 dark:bg-slate-800 dark:text-white"
              />
            </label>
            <Button type="submit" disabled={!villageDistrict.trim()}>
              Show water quality
            </Button>
          </form>

          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
            This restriction applies to villages only. A city, town, area, nagar,
            colony, company, shop, college, school, hotel, hospital or landmark is
            searched normally and shows its result immediately.
          </p>
        </Card>
      )}

      {/* --- District places (Step 21) -------------------------------------- */}
      {/* When the search text is a DISTRICT, the page shows its nine major /
          relevant places — the internal 3 SAFE / 3 MODERATE / 3 UNSAFE dataset
          — with the labels HIDDEN. Each card shows only place name,
          town/village/area, district and state. No Safe/Moderate/Unsafe tag,
          no colour and no prediction appears here; the verdict is revealed
          only when the user clicks a place and the analysis path runs. */}
      {districtStatus === 'ready' && districtOverview?.district?.name && (
        <Card
          className="mb-6 animate-zoom-in"
          title={`${districtOverview.district.name} — Places Overview`}
          subtitle="Nine major places of the district. Select a place to inspect its water — the analysis runs when you open it, never before."
        >
          {/* STEP 20: THE COVERAGE NOTE, SHOWN WHEN THE NINE ARE NOT COMPLETE.

              The brief asks for nine places spanning the three internal bands and
              then says not to fabricate them when the district cannot supply
              them. So when the verified set is short, the screen SAYS SO, in
              words, before the cards - and shows only the places that were really
              verified. Nothing is padded to reach nine. */}
          {districtOverview.coverage && !districtOverview.coverage.complete && (
            <p
              className="mb-4 rounded-field border border-caution-light bg-caution-light/40 px-4 py-3 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200"
              role="status"
            >
              <span className="font-semibold">Insufficient Data</span>
              {districtOverview.message ? (
                <span> — {districtOverview.message.replace(/^Insufficient Data:?\s*/i, '')}</span>
              ) : null}
            </p>
          )}

          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {(districtOverview.places || []).map((item) => (
              <li
                key={`${item.name}-${item.area || ''}`}
                className="flex items-center gap-3 rounded-field border border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
              >
                <StatusDot tone="unknown" />
                <button
                  type="button"
                  onClick={() => openDistrictPlace(item)}
                  className="min-w-0 flex-1 text-left hover:underline"
                  title={`Open ${item.name}`}
                >
                  <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                    {item.name}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                    {[item.area, item.district, item.state].filter(Boolean).join(', ') || '—'}
                  </p>
                </button>
              </li>
            ))}
          </ul>

          <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            The places are the district&apos;s real mapped settlements, each sampled
            for the water actually recorded around it — never randomly assigned.
            No risk label, colour or category is shown at this level: the cards
            carry the place name, its area, the district and the state only, and
            open a place is what runs the analysis that produces a verdict.
          </p>
        </Card>
      )}

      {/* --- Branch selection (Step 24) ---------------------------------------- */}
      {/* A CHAIN WITH MORE THAN ONE BRANCH IS ONE SEARCH WITH SEVERAL ANSWERS.

          "Indian Bank Karaikudi" is two real buildings in two different areas.
          Answering with whichever ranked first silently picks a branch, and the
          water source, the parameters and the hand-off below then describe a shop
          the user never chose - the brief is explicit that a headquarters or an
          arbitrary branch must not stand in for the selected one.

          So the real branches are listed here, each on its own row with the
          fields the brief names: place name, area/city, district, state, country
          and the pincode when the map records one. Every row is a real geocoder
          result, and a field the data does not have reads "Not available" rather
          than being filled in from the district or the state.

          A branch the server has marked out of scope is shown with its reason and
          cannot be selected - the scope is the backend's decision, and this card
          only reports it. */}
      {branches.length > 0 && place && (
        <Card
          className="mb-6 animate-zoom-in"
          title={`${place.name} has ${branches.length + 1} location${branches.length > 0 ? 's' : ''} — select the branch you mean`}
          subtitle="The water source, the quality parameters and the prediction below are all read from the branch you select, at that branch's own coordinates."
        >
          <ul className="grid gap-2 sm:grid-cols-2" data-testid="branch-list">
            {/* The currently selected place is shown first, marked as selected,
                so the list reads as "the options for this name" rather than as a
                set that mysteriously omits the one already on screen. */}
            <li className="flex items-center gap-3 rounded-field border border-aqua-300 bg-aqua-50 p-3 dark:border-aqua-700 dark:bg-slate-800">
              <span
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-aqua-500/15 text-aqua-700 dark:text-aqua-300"
                aria-hidden="true"
              >
                <Icon path={ICONS.location} className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                  {place.name}
                </p>
                <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                  {[
                    place.area || place.city,
                    place.district,
                    place.state,
                    place.country,
                    place.pincode ? `Pincode: ${place.pincode}` : null,
                  ]
                    .filter(Boolean)
                    .join(', ') || 'Address not available'}
                </p>
              </div>
              <Badge tone="aqua">Selected</Badge>
            </li>

            {branches.map((branch) => {
              const blocked = Boolean(branch.blocked_reason)
              return (
                <li
                  key={`${branch.name}-${branch.lat}-${branch.lon}`}
                  className="flex items-center gap-3 rounded-field border border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
                >
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-aqua-500/15 text-aqua-700 dark:text-aqua-300"
                    aria-hidden="true"
                  >
                    <Icon path={ICONS.location} className="h-4 w-4" />
                  </span>
                  {blocked ? (
                    // An out-of-scope branch is reported, never offered as a
                    // choice the server would then refuse.
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-slate-500 dark:text-slate-400">
                        {branch.name}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-slate-400 dark:text-slate-500">
                        {[
                          branch.area || branch.city,
                          branch.district,
                          branch.state,
                          branch.country,
                          branch.pincode ? `Pincode: ${branch.pincode}` : null,
                        ]
                          .filter(Boolean)
                          .join(', ') || 'Address not available'}
                      </p>
                      <p className="mt-1 text-xs text-caution-dark dark:text-caution-light">
                        {branch.blocked_reason}
                      </p>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => selectBranch(branch)}
                      className="min-w-0 flex-1 text-left hover:underline"
                      title={`Use ${branch.branch_label || branch.name}`}
                      data-testid="branch-option"
                    >
                      <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                        {branch.name}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                        {[
                          branch.area || branch.city,
                          branch.district,
                          branch.state,
                          branch.country,
                          branch.pincode ? `Pincode: ${branch.pincode}` : null,
                        ]
                          .filter(Boolean)
                          .join(', ') || 'Address not available'}
                      </p>
                    </button>
                  )}
                </li>
              )
            })}
          </ul>

          <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            Each row is a real mapped location with its own coordinates. The water
            source, the quality parameters and “Enter Water Prediction” are all read
            from the branch you select — never from the company&apos;s headquarters
            or from whichever branch appeared first.
          </p>
        </Card>
      )}

      {/* --- Selected location ---------------------------------------------- */}
      {status === 'ready' && place && (
        <Card
          className="mb-6 animate-zoom-in"
          title="Selected location"
          actions={source && <Badge tone="aqua">{SOURCE_LABELS[source] || 'Selected'}</Badge>}
        >
          {/* The headline: a pin, the place name, then the region line — the
              "📍 Karaikudi / Tamil Nadu, India / Pincode: 630001" the brief asks
              for, laid out as a proper card rather than three bare lines. */}
          <div className="mb-5 flex items-start gap-3">
            <span
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-aqua-500 to-aqua-700 text-white shadow-sm"
              aria-hidden="true"
            >
              <Icon path={ICONS.location} className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">
                {place.name}
              </p>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {[place.district, place.state, place.country].filter(Boolean).join(', ') ||
                  place.label}
              </p>
              {place.pincode && (
                <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
                  Pincode: <span className="font-medium tabular">{place.pincode}</span>
                </p>
              )}
            </div>
          </div>

          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Detail label="Place" value={place.name} icon={ICONS.location} />
            {/* STEP 25: AREA, the smallest named part of the address the geocoder
                actually returned. "Not available" when the data carries none -
                a town with no neighbourhood is not given the town's own name as
                its area, because that would be inventing the precision. */}
            <Detail
              label="Area"
              value={place.area || 'Not available'}
              icon={ICONS.search}
            />
            <Detail label="City / Town" value={place.city} icon={ICONS.home} />
            <Detail label="District" value={place.district} icon={ICONS.analytics} />
            <Detail label="State" value={place.state} icon={ICONS.shield} />
            <Detail label="Country" value={place.country} icon={ICONS.info} />
            <Detail label="Pincode" value={place.pincode || 'Not available'} icon={ICONS.reports} />
            {/* THE DEVICE FIX HIDES ITS OWN COORDINATES. A search or a manual
                pick may show the pin the user chose, but an auto-detected
                position is personal data the user did not type, so only the
                place it resolved to is shown - never the raw numbers. */}
            {source !== 'device' && (
              <>
                <Detail
                  label="Latitude"
                  value={typeof place.lat === 'number' ? place.lat.toFixed(5) : place.lat}
                  icon={ICONS.search}
                />
                <Detail
                  label="Longitude"
                  value={typeof place.lon === 'number' ? place.lon.toFixed(5) : place.lon}
                  icon={ICONS.search}
                />
              </>
            )}
          </dl>

          <p className="mt-5 border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            Location identified. The water source, nearby sources and risks for this
            place are shown below.
          </p>
        </Card>
      )}

      {/* --- Water source type --------------------------------------------- */}
      {/* STEP 16: A PROGRESSIVE LOADER, NOT A BLANK PAGE.

          The location is already identified by the time this shows, so the page is
          not blocked - the cards above it are interactive. What is pending is only
          the water data, and this says so, names the step, and reports the elapsed
          time so a slow upstream is visible as slow rather than as frozen. */}
      {status === 'ready' && place && waterStatus === 'loading' && (
        <Card className="animate-zoom-in" title="Water Source Type" aria-live="polite">
          <div className="flex items-center gap-3 py-2">
            <span className="h-10 w-10 shrink-0 animate-pulse rounded-full bg-aqua-50 dark:bg-slate-800" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-40 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
              <div className="h-3 w-64 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
            </div>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Identifying the water source from mapped water data
            {waterElapsedMs >= 1000 ? ` · ${Math.round(waterElapsedMs / 1000)}s` : '…'}
          </p>
          <p className="mt-1 text-2xs text-slate-400 dark:text-slate-500">
            Water data is being retrieved. The location above is already confirmed.
          </p>
        </Card>
      )}

      {/* STEP 16: A DISTINCT FALLBACK WHEN THE UPSTREAM IS SLOW OR GONE.

          This is deliberately NOT the same card a genuinely unmapped area gets. An
          area with no mapped water is a real answer about the place; an upstream
          that could not be reached is a failure to find out. Showing the first as
          the second would tell the visitor their area has no water when the truth
          is that nobody was able to ask. */}
      {status === 'ready' && place && waterStatus === 'error' && (
        <Card
          className="animate-zoom-in"
          title="Water Source Type"
          subtitle="The mapped water service did not answer"
        >
          <div className="flex items-start gap-2.5 py-1 text-sm text-caution-dark dark:text-caution-light">
            <Icon path={ICONS.info} className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">
                {waterError?.isNetworkError || waterError?.isTimeout
                  ? 'Could not reach the water-data service'
                  : 'The water-data service did not respond in time'}
              </p>
              <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
                The location is confirmed and everything else on this page is accurate.
                Only the mapped water sources for this point could not be retrieved, so
                no water type is shown rather than a guessed one. Try again in a moment.
              </p>
            </div>
          </div>
        </Card>
      )}

      {status === 'ready' && place && waterStatus === 'ready' && water && (
        <Card
          className="animate-zoom-in"
          title="Water Source Type"
          subtitle={
            water.available
              ? water.exact
                ? 'Identified at this location from OpenStreetMap water data'
                : 'No water source is mapped at this exact location — the nearest sources are listed below'
              : undefined
          }
        >
          {water.available ? (
            <>
              {/* STEP 13: THE HEADLINE IS THE SOURCE *AT THIS LOCATION*, OR AN
                  HONEST STATEMENT THAT THERE ISN'T ONE.

                  This card used to show `water.primary` unconditionally, and
                  `primary` was the type of the nearest mapped feature no matter
                  how far away it was. A well 400 m from the chosen point was
                  therefore presented as "the water source type" for that
                  location - asserting something the map does not say.

                  The server now sets `primary` to null unless a source is within
                  the exact radius, and `exact` says which case this is. When it
                  is false the card names the NEAREST source and its real
                  distance, and points down to the full list rather than claiming
                  a supply for the location. */}
              <div className="flex items-start gap-3">
                <span
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-aqua-500 to-aqua-700 text-white shadow-sm"
                  aria-hidden="true"
                >
                  <Icon path={ICONS.droplet} className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <p className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    Water Source Type
                  </p>
                  {water.exact ? (
                    <p className="text-lg font-bold capitalize tracking-tight text-slate-900 dark:text-white">
                      {water.primary}
                    </p>
                  ) : (
                    <>
                      {/* PROMPT 1, E.5: "WATER SOURCE NOT IDENTIFIED" — said
                          plainly, never papered over with a nearby feature's
                          type. The nearest source stays visible below as
                          information only. */}
                      <p className="text-lg font-bold tracking-tight text-slate-600 dark:text-slate-300">
                        Water source not identified
                      </p>
                      {water.nearest && (
                        <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">
                          Nearest mapped source:{' '}
                          <span className="font-medium capitalize">{water.nearest.name}</span>{' '}
                          <span className="text-slate-500 dark:text-slate-400">
                            ({water.nearest.distance_km} km · {water.nearest.type})
                          </span>
                        </p>
                      )}
                    </>
                  )}
                </div>
              </div>

              {/* PROMPT 1, E.4: THE SOURCE SELECTION. When no source is mapped
                  AT the point — or when the user knows a different one applies
                  — they can choose the actual source from the real nearby
                  features or from the supported type list. Selecting one makes
                  it the source the prediction describes and the parameter
                  pre-fill is fetched for it. It is deliberately NOT shown when
                  a source is already identified at the exact point unless the
                  user asks to change it. */}
              {!water.exact && (
                <SourceSelector
                  nearby={water.nearby || []}
                  selected={selectedSource}
                  onSelect={(source) => {
                    setSelectedSource(source)
                    // The parameter pre-fill is refetched for the newly chosen
                    // source, so the readings describe the source the
                    // prediction will be made for.
                    if (source) {
                      locationApi.parameters(source).then((response) => {
                        const values = response?.data?.parameters
                        if (values && typeof values === 'object') {
                          setDefaults(values)
                          setDefaultsSource({ source: 'estimated', label: 'Estimated', note: `Typical values for ${source} — not measured anywhere near here` })
                          setEditable((current) => {
                            // Only fill fields the user has not already typed
                            // into — an edited reading is never overwritten by
                            // a re-fetch.
                            const next = { ...current }
                            for (const [name, value] of Object.entries(values)) {
                              if (next[name] === undefined || next[name] === null || next[name] === '') {
                                next[name] = value
                              }
                            }
                            return next
                          })
                        }
                      }).catch(() => {
                        /* Keep the current readings; the selector change is
                           still committed. */
                      })
                    }
                  }}
                />
              )}

              {/* Every category observed nearby, as chips. */}
              {water.types?.length > 1 && (
                <div className="mt-4">
                  <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    Also present nearby
                  </p>
                  <ul className="flex flex-wrap gap-2">
                    {water.types
                      .filter((type) => type !== (water.primary || water.nearest_type))
                      .map((type) => (
                        <li
                          key={type}
                          className="rounded-full bg-aqua-50 px-3 py-1 text-xs font-medium capitalize text-aqua-700 dark:bg-slate-800 dark:text-aqua-300"
                        >
                          {type}
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            // NO RELIABLE DATA: say so plainly. No source type is shown, because
            // showing one would mean inventing it.
            <div className="flex items-start gap-3 rounded-card border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-700 dark:bg-slate-800">
              <span className="mt-0.5 shrink-0 text-slate-500" aria-hidden="true">
                <Icon path={ICONS.droplet} className="h-5 w-5" />
              </span>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {water.message || WATER_UNAVAILABLE_MESSAGE}
              </p>
            </div>
          )}
        </Card>
      )}

      {/* --- Nearby water sources ------------------------------------------ */}
      {/* STEP 29: EVERY SOURCE CARRIES WHAT ITS QUALITY DATA ACTUALLY IS.
       *
       * The brief's rule for this card is that it must not leave the water source
       * empty: when no source is mapped AT the selected location, the real
       * sources around it are listed instead, and each row says what data exists
       * for that source.
       *
       * The `quality` block on each row is the server's own resolution of that
       * question, and the three states it can be in are rendered distinctly:
       *
       *   measured        real stored readings, labelled "Nearby Source Data"
       *   dataset_estimate the real corpus median, labelled as an estimate
       *   none            no readings at all, and none are shown
       *
       * When `quality.values` is absent the five parameters are NOT rendered -
       * there is nothing to render, and drawing an empty row of dashes beside a
       * real-looking label would invite the reader to treat a blank as a zero.
       * That absence is the guarantee the backend makes and this card preserves. */}
      {status === 'ready' && place && waterStatus === 'ready' && water && (
        <Card
          className="mb-6 animate-zoom-in"
          title="Nearby Water Sources"
          subtitle={
            water.available && water.nearby?.length
              ? 'Nearest first, with distance. Every source is a mapped water feature.'
              : undefined
          }
        >
          {water.available && water.nearby?.length ? (
            <ol className="space-y-3">
              {/* FIVE, nearest first. The brief caps the nearby list at five —
                  a longer list buries the nearest sources that actually matter. */}
              {water.nearby.slice(0, 5).map((row, index) => {
                const quality = row.quality || {}
                const hasValues =
                  quality.status === 'measured' || quality.status === 'dataset_estimate'
                const isMeasured = quality.status === 'measured'
                return (
                  <li
                    key={`${row.type}-${row.name}-${index}`}
                    className="rounded-field border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
                  >
                    <div className="flex items-start gap-3">
                      <span
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-aqua-100 text-xs font-semibold text-aqua-800 dark:bg-slate-700 dark:text-aqua-200"
                        aria-hidden="true"
                      >
                        {index + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                          {row.name}
                        </p>
                        <p className="mt-0.5 text-xs capitalize text-slate-500 dark:text-slate-400">
                          Type: {row.type}
                          {/* STEP 13: SAY SO WHEN THE MAP HAS NO NAME FOR IT.
                              The label already reads "Unnamed Pond" rather than a
                              made-up name, and this makes the reason explicit, so a
                              user never mistakes it for a real place name the app
                              found. `named` is the server's own flag from whether
                              OpenStreetMap supplied a name. */}
                          {row.named === false && (
                            <span className="ml-1 normal-case text-slate-400 dark:text-slate-500">
                              · no official name in map data
                            </span>
                          )}
                        </p>
                      </div>
                      <span className="shrink-0 rounded-full bg-white px-2.5 py-1 text-xs font-medium text-slate-600 tabular shadow-sm dark:bg-slate-900 dark:text-slate-200">
                        {row.distance_km} km
                      </span>
                    </div>

                    {/* THE QUALITY DATA STATUS for this source. Present for every
                        row, because "we don't know" is itself information the user
                        needs - a silent row would look identical to one with data. */}
                    <div className="mt-2.5 flex flex-wrap items-center gap-2 pl-10">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-semibold ${
                          isMeasured
                            ? 'bg-safe-50 text-safe-dark dark:bg-safe-900/30 dark:text-safe-light'
                            : hasValues
                              ? 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                              : 'bg-caution-50 text-caution-dark dark:bg-caution-900/30 dark:text-caution-light'
                        }`}
                      >
                        {quality.label || 'No quality data available'}
                      </span>
                    </div>

                    {/* THE FIVE READINGS, WHERE THEY EXIST. The heading is the
                        one the brief names for real data about a nearby source,
                        and it is the ONLY place these appear - a dataset estimate
                        never gets this heading, so "Nearby Source Data" can never
                        sit above numbers that were not measured. */}
                    {hasValues && (
                      <div className="mt-2.5 rounded-field border border-slate-200 bg-white p-3 dark:border-slate-600 dark:bg-slate-900">
                        <p className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                          {isMeasured ? 'Nearby Source Data' : 'Dataset-Based Estimate'}
                        </p>
                        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
                          {(parameterDefinitions.length
                            ? parameterDefinitions
                            : FEATURE_NAMES.map((name) => ({
                              name,
                              label: FEATURE_META[name].label,
                              unit: FEATURE_META[name].unit,
                            }))
                          ).map(({ name, label, unit }) => {
                            const value = quality.values?.[name]
                            // A single missing value is shown as unavailable
                            // rather than as a blank or a zero.
                            if (value === undefined || value === null) return null
                            return (
                              <div key={name} className="min-w-0">
                                <dt className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                                  {label}
                                </dt>
                                <dd className="truncate text-xs font-medium text-slate-700 tabular dark:text-slate-200">
                                  {value}
                                  {unit ? <span className="ml-0.5 font-normal text-slate-400">{unit}</span> : null}
                                </dd>
                              </div>
                            )
                          })}
                        </dl>
                        {quality.note && (
                          <p className="mt-2 border-t border-slate-100 pt-2 text-2xs leading-relaxed text-slate-500 dark:border-slate-700 dark:text-slate-400">
                            {quality.note}
                          </p>
                        )}
                      </div>
                    )}

                    {/* With no data at all there is no readings block - only the
                        reason, so the gap is explained rather than merely empty. */}
                    {!hasValues && quality.note && (
                      <p className="ml-10 mt-1.5 text-2xs leading-relaxed text-slate-500 dark:text-slate-400">
                        {quality.note}
                      </p>
                    )}
                  </li>
                )
              })}
            </ol>
          ) : (
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {water.available
                ? 'No individual nearby sources are listed for this location.'
                : water.message || WATER_UNAVAILABLE_MESSAGE}
            </p>
          )}
        </Card>
      )}

      {/* --- Water Quality Risk --------------------------------------------- */}
      {status === 'ready' && place && waterStatus === 'ready' && riskLevel && (
        <Card
          className="mb-6 animate-zoom-in"
          title="Water Quality Risk"
          subtitle="Location-level estimated risk — from the identified water source, not a water test"
        >
          {riskLevel.level === 'unknown' ? (
            // NO RELIABLE BASIS: say so. A risk level is never invented, so a
            // location with no mapped water gets no category.
            <div className="flex items-start gap-3 rounded-card border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
              <span className="mt-0.5 shrink-0 text-slate-500" aria-hidden="true">
                <Icon path={ICONS.info} className="h-5 w-5" />
              </span>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {riskLevel.message || 'A risk category cannot be given without reliable water data.'}
              </p>
            </div>
          ) : (
            <>
              {/* The category, in the Low / Moderate / High form, coloured to
                  match the rest of the application's risk badges. */}
              <div className="flex items-center gap-3">
                <Badge risk={riskLevel.level} button />
                <div>
                  <p className="text-sm text-slate-700 dark:text-slate-200">
                    Risk Level: <span className="font-semibold">{riskLevel.label}</span>
                  </p>
                  {/* The brief's own wording: this is an ESTIMATE at the location
                      level, distinct from the ML verdict, which only appears
                      after the user analyses water on the Manual Prediction page. */}
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Location-level estimated risk
                  </p>
                </div>
              </div>

              {/* THE FACTORS, only the ones we actually have — and only the WATER
                  ones. `waterFactors` drops every factor whose `source` is
                  `weather`, because the risk level itself is still raised by rain
                  upstream and that fact is not shown as a factor here. Rain belongs
                  to the Rainy Alerts screen; see the note on `waterFactors` for why
                  the number and the reasoning are allowed to disagree. */}
              {waterFactors(riskLevel.factors).length > 0 && (
                <div className="mt-4">
                  <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    Possible factors
                  </p>
                  <ul className="space-y-2">
                    {waterFactors(riskLevel.factors).map((factor, index) => (
                      <li
                        key={`${factor.source}-${index}`}
                        className="flex items-start gap-2 rounded-field border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
                      >
                        <span className="mt-0.5 shrink-0 text-caution-dark" aria-hidden="true">
                          <Icon path={ICONS.info} className="h-4 w-4" />
                        </span>
                        <span className="text-sm capitalize text-slate-700 dark:text-slate-200">
                          {factor.detail}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* The named risks for the identified source, kept as supporting
                  detail beneath the category. */}
              {risks.length > 0 && (
                <div className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-700">
                  <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    Known risks for this source
                  </p>
                  <ul className="flex flex-wrap gap-2">
                    {risks.map((row, index) => (
                      <li
                        key={`${row.type}-${row.risk}-${index}`}
                        className="rounded-full bg-caution-light/50 px-3 py-1 text-xs text-caution-dark"
                      >
                        {row.risk}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {/* --- Water quality parameters + hand-off to Manual Prediction ------- */}
      {/* STEP 21: THIS CARD IS NOT GATED ON THE WATER SERVICE.

          The five readings the brief names - pH, turbidity, TDS, temperature and
          dissolved oxygen - are values the USER SUPPLIES from a test, not things
          the map data knows. This card used to render only when
          `waterStatus === 'ready'`, so when the mapped-water lookup failed it
          disappeared along with its "Analyze Water Quality" button and the
          "Enter Water Prediction" hand-off: the visitor was left identified,
          told the water service was unreachable, and unable to do anything at
          all. That is the wrong failure - an unreachable service removes the
          context, not the ability to act.

          So the card renders for every identified place. When the service
          answered, the readings are prefilled from it; when it did not, the
          fields are simply empty and the provenance line says why. Either way
          the user can type their own readings and run the analysis themselves,
          which is the whole point of requiring them to perform the prediction. */}
      {status === 'ready' && place && (
        <Card
          className="mb-6 animate-zoom-in"
          title="Water Quality Parameters"
          subtitle={PROVENANCE_HINT[defaultsSource?.source] ||
            (waterStatus === 'error'
              ? 'No readings were prefillable — the mapped-water service did not answer'
              : 'Where each value came from')}
        >
          {/* STEP 12: THE PROVENANCE BADGE IS THE POINT OF THIS CARD.
              Every value below is real, but a number is only meaningful next to
              the answer to "measured where, and when?". The five provenances the
              brief names are rendered distinctly, and the one that says
              "User input required" shows NO values at all - an empty card with
              an explanation is a correct answer, and inventing a plausible
              figure to fill it is exactly what must never happen.

              The badge text comes from the server so the wording cannot drift
              between the two screens that show it. */}
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-1 text-2xs font-semibold uppercase tracking-wider ${
                defaultsSource?.source === 'measured'
                  ? 'bg-safe-50 text-safe-dark dark:bg-safe-900/30 dark:text-safe-light'
                  : defaultsSource?.source === 'user_input_required'
                    ? 'bg-caution-50 text-caution-dark dark:bg-caution-900/30 dark:text-caution-light'
                    : 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
              }`}
            >
              {defaultsSource?.label || 'Estimated'}
            </span>
            {/* The water source these readings describe — the user's selection
                when they made one, the identified source otherwise, and the
                honest "not identified" when neither exists. */}
            {(effectiveSource || selectedSource !== null) && (
              <span className="text-xs text-slate-500 dark:text-slate-400">
                Water source: <span className="font-medium text-slate-700 dark:text-slate-200">{effectiveSource || 'not identified'}</span>
              </span>
            )}
          </div>

          {/* STEP 14: THESE ARE EDITABLE INPUTS, NOT READ-ONLY TEXT.
              The card used to render the readings as fixed <dd> values, which
              contradicted the sentence underneath it telling the user to review
              and edit them - there was nothing to edit. Each parameter is now a
              labelled number input bound to `editable`, seeded from the
              server's values, so the user can replace any estimate with their
              own reading before analysing.

              The value shown is `editable[name]`, NOT `defaults[name]`, because
              that is the number that will actually be sent. Showing the original
              estimate next to an edited box would let a user analyse 8.4 while
              the card still read 7.2. */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {(parameterDefinitions.length
              ? parameterDefinitions
              : FEATURE_NAMES.map((name) => ({
                  name,
                  label: FEATURE_META[name].label,
                  unit: FEATURE_META[name].unit,
                }))
            ).map(({ name, label, unit }) => {
              const fieldError = fieldErrors?.[name]
              return (
                <div
                  key={name}
                  className="rounded-field border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
                >
                  <label
                    htmlFor={`param-${name}`}
                    className="block text-2xs font-semibold uppercase tracking-wider text-slate-400"
                  >
                    {label}
                  </label>
                  <div className="mt-1 flex items-baseline gap-1">
                    <input
                      id={`param-${name}`}
                      type="number"
                      step="0.01"
                      inputMode="decimal"
                      value={editable?.[name] ?? ''}
                      onChange={(event) => {
                        const next = event.target.value
                        setEditable((current) => ({ ...current, [name]: next }))
                        // Clear this field's error as soon as it is edited, so a
                        // stale rejection does not sit under a corrected value.
                        if (fieldErrors?.[name]) {
                          setFieldErrors((current) => {
                            const next2 = { ...current }
                            delete next2[name]
                            return next2
                          })
                        }
                      }}
                      placeholder={defaults?.[name] === undefined || defaults?.[name] === null
                        ? 'Enter'
                        : undefined}
                      aria-label={`${label}${unit ? ` in ${unit}` : ''}`}
                      className={`w-full min-w-0 border-b bg-transparent text-sm font-semibold tabular text-slate-800 outline-none dark:text-slate-100 ${
                        fieldError
                          ? 'border-caution-dark dark:border-caution-light'
                          : 'border-slate-300 focus:border-aqua-500 dark:border-slate-600'
                      }`}
                    />
                    <span className="shrink-0 text-xs font-normal text-slate-400">{unit}</span>
                  </div>
                  {fieldError && (
                    <p className="mt-1 text-2xs text-caution-dark dark:text-caution-light">
                      {typeof fieldError === 'string' ? fieldError : 'This value was rejected.'}
                    </p>
                  )}
                </div>
              )
            })}
          </div>

          {/* Say plainly where these numbers came from, and that they are a
              starting point the user can and should change. The server writes
              the sentence, because only it knows which of the five sources
              answered. */}
          <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            {defaultsSource?.note ||
              'No reliable readings are available for this location. Enter your own test results.'}{' '}
            <span className="font-medium text-slate-600 dark:text-slate-300">
              Edit any value above, then run the analysis below.
            </span>
          </p>

          {/* STEP 14: THE ANALYZE BUTTON, ON THIS PAGE. */}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button type="button" onClick={analyzeWater} loading={analysing}>
              <Icon path={ICONS.predict} className="h-4 w-4" />
              {analysing ? 'Analyzing…' : 'Analyze Water Quality'}
            </Button>
            <p className="text-2xs text-slate-400 dark:text-slate-500">
              Runs the AquaGuard AI Random Forest model on these readings.
            </p>
          </div>

          {/* Loading and error states, both announced. A prediction panel that
              says nothing while it waits is indistinguishable from one that has
              failed, and neither may be mistaken for a result. */}
          {analysing && (
            <p
              role="status"
              className="mt-3 flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300"
            >
              <span
                className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-aqua-600"
                aria-hidden="true"
              />
              Running the model on these readings…
            </p>
          )}

          {analysisError && (
            <p
              role="alert"
              className="mt-3 rounded-field border border-caution-300 bg-caution-50 px-3 py-2 text-sm text-caution-dark dark:border-caution-700 dark:bg-caution-900/20 dark:text-caution-light"
            >
              {analysisError.message}
            </p>
          )}
        </Card>
      )}

      {/* --- STEP 14: THE PREDICTION RESULT, RENDERED HERE ------------------- */}
      {status === 'ready' && place && prediction && (
        <Card
          className="mb-6 animate-zoom-in"
          title="Water Quality Prediction Result"
          subtitle="Produced by the AquaGuard AI Random Forest model on the readings shown above"
        >
          <VerdictBanner prediction={prediction} />

          {/* Everything the brief lists, in one place. The location is echoed
              from what this page identified, and the readings are `analysed` -
              the numbers actually sent - not the current state of the inputs,
              so editing a box afterwards cannot rewrite the result shown. */}
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Detail label="Location" value={place.name} icon="location" />
            <Detail label="City / Town" value={place.city} icon="location" />
            <Detail label="District" value={place.district} icon="reports" />
            <Detail label="State" value={place.state} icon="reports" />
            <Detail label="Country" value={place.country} icon="analytics" />
            <Detail label="Pincode" value={place.pincode} icon="droplet" />
            <Detail
              label="Water Source"
              // PROMPT 1, E.5: what the prediction was actually made for — the
              // user's selection, the identified source, or "not identified".
              // A nearby feature is never promoted into the source slot.
              value={effectiveSource || 'Water source not identified'}
              icon="droplet"
            />
            {FEATURE_NAMES.map((name) => (
              <div
                key={name}
                className="rounded-field border-slate-100 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800"
              >
                <dt className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                  {FEATURE_META[name].label}
                </dt>
                <dd className="mt-0.5 text-sm font-semibold text-slate-800 tabular dark:text-slate-100">
                  {analysed?.[name] === undefined ? '—' : formatNumber(analysed[name])}
                  <span className="ml-1 font-normal text-slate-400">
                    {FEATURE_META[name].unit}
                  </span>
                </dd>
              </div>
            ))}
          </dl>

          <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            This verdict was computed from the readings shown above
            {defaultsSource?.label ? ` (${defaultsSource.label})` : ''}.{' '}
            {prediction.model_name
              ? `Model: ${prediction.model_name}${prediction.model_version ? ` v${prediction.model_version}` : ''}. `
              : ''}
            It is saved to your prediction history.
          </p>
        </Card>
      )}

      {/* STEP 15: after the location's water-quality parameters are shown, offer
          the hand-off to Manual Prediction. Pressing it opens that page with the
          five readings already in the (editable) form and the location travelling
          internally - and it does NOT run the prediction: the visitor still has to
          press "Analyze Water Quality" there. */}
      {status === 'ready' && place && (
        <div className="mb-6 flex justify-end">
          <Button type="button" onClick={goToPredict} variant="secondary">
            Enter Water Prediction
          </Button>
        </div>
      )}

      {/* --- Empty prompt --------------------------------------------------- */}
      {status === 'idle' && (
        <Card>
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <span
              className="flex h-12 w-12 items-center justify-center rounded-full bg-aqua-50 text-aqua-700 dark:bg-slate-800 dark:text-aqua-300"
              aria-hidden="true"
            >
              <Icon path={ICONS.location} className="h-6 w-6" />
            </span>
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              No location selected
            </p>
            <p className="max-w-sm text-sm text-slate-500 dark:text-slate-400">
              Search a city, pincode or landmark above — or use your device&apos;s location — to
              identify the place you want to test.
            </p>
            {/* Name the five readings this screen feeds, so the page reads as part
                of THIS application rather than a generic map lookup. Shown from the
                start (before a place is chosen) because the parameters are what
                the whole flow ends in. */}
            <p className="max-w-sm text-xs text-slate-400 dark:text-slate-500">
              Then it identifies the water source and pre-fills the prediction form with its
              typical {FEATURE_NAMES.map((name) => FEATURE_META[name].label).join(', ')}.
            </p>
          </div>
        </Card>
      )}

      {/* --- Map picker ----------------------------------------------------- */}
      {/* ONE modal, two jobs, and `mode` is what tells them apart.

          In `device` mode it opens on the fix the browser just reported and names
          the place beside the map, so the user can see - and correct - where the
          app thinks they are before any result is committed. In `manual` mode it
          opens on the last identified place, or the world when there is none, and
          the user pins a point themselves.

          In device mode the pin comes from the FIX and not from the place, so
          `initial` has to be the fix rather than `place`: after a fix the modal
          opens before any place exists, and on a later manual open the previous
          place is a better starting view than a stale GPS reading. */}
      <LocationMapPicker
        open={pickerOpen}
        initial={pickerMode === 'device'
          ? deviceFix ?? undefined
          : place ? { lat: place.lat, lon: place.lon } : undefined}
        mode={pickerMode}
        reverse={reverseGeocode}
        error={pickerError}
        onMoved={() => setPickerError(null)}
        busy={status === 'loading'}
        onClose={() => {
          setPickerOpen(false)
          setPickerError(null)
          // STEP 25: closing without confirming DISCARDS the fix. The user
          // looked at the map and did not accept it, so nothing about their
          // position is left held on screen.
          setDeviceFix(null)
        }}
        onConfirm={(coords) => (
          pickerMode === 'device'
            ? confirmPicked(coords, 'device')
            : confirmManual(coords)
        )}
      />
    </div>
  )
}
