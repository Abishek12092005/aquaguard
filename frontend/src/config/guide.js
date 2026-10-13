/**
 * Home-page guide content.
 *
 * One list, consumed twice: the auto-scrolling cards at the top of the Home page
 * and the step-by-step guide below them. Keeping it in one place means the two
 * can never disagree about what the workflow is.
 *
 * Everything here is descriptive of the app's actual behaviour — the parameter
 * names and units match `FEATURE_META`, and the verdict labels match the model's
 * three classes (SAFE / MODERATE / UNSAFE). It is deliberately not marketing copy:
 * a user reads these cards to learn what to type and what the answer will mean.
 */

/** The five parameters the model accepts, in submission order. */
export const GUIDE_INPUTS = [
  {
    key: 'ph',
    label: 'pH',
    unit: 'pH',
    range: '0 – 14',
    good: '6.5 – 8.5',
    note: 'Acidity or alkalinity. Below 6.5 the water is corrosive; above 8.5 it tastes soapy and scales pipes.',
  },
  {
    key: 'turbidity',
    label: 'Turbidity',
    unit: 'NTU',
    range: '0 – 1000',
    good: 'Under 5',
    note: 'How cloudy the sample is. Cloudiness shelters bacteria from disinfection, so it matters even when nothing else is wrong.',
  },
  {
    key: 'tds',
    label: 'Total Dissolved Solids',
    unit: 'mg/L',
    range: '0 – 50000',
    good: 'Under 500',
    note: 'Dissolved salts and minerals. High values usually mean the water has picked up everything it travelled through.',
  },
  {
    key: 'temperature',
    label: 'Temperature',
    unit: '°C',
    range: '-5 – 100',
    good: '10 – 25',
    note: 'Warm water holds less oxygen and grows bacteria faster, so it shifts the verdict even on its own.',
  },
  {
    key: 'dissolved_oxygen',
    label: 'Dissolved Oxygen',
    unit: 'mg/L',
    range: '0 – 20',
    good: '6.5 – 9.5',
    note: 'Oxygen held in the water. Low readings point to stagnant or heavily loaded water.',
  },
]

/**
 * The walkthrough, in order.
 *
 * `step` is a number rather than a string so the card rail can show the progress
 * ("3 of 6") without parsing it.
 */
export const GUIDE_STEPS = [
  {
    step: 1,
    title: 'Open Manual Prediction',
    icon: 'predict',
    body: 'Open Manual Prediction from the sidebar and type the readings yourself. The form is generated from the server, so the fields you see are exactly the ones the model was trained on.',
  },
  {
    step: 2,
    title: 'Enter the five readings',
    icon: 'analytics',
    body: 'Type pH, turbidity, TDS, temperature and dissolved oxygen from your test strip, meter or lab report. Fill as many as you have — the app tells you how much each missing field would have helped.',
    detail: 'Partial submissions are supported; the confidence figure drops to reflect what is missing.',
  },
  {
    step: 3,
    title: 'Check the ranges',
    icon: 'shield',
    body: 'Each field accepts only its own valid span, so a typo like pH 72 is caught before it is submitted rather than quietly becoming a nonsense answer.',
    detail: 'pH 0–14 · Turbidity 0–1000 NTU · TDS 0–50000 mg/L · Temp −5–100 °C · DO 0–20 mg/L.',
  },
  {
    step: 4,
    title: 'Submit and read the verdict',
    icon: 'check',
    body: 'The model returns one of three verdicts — SAFE, MODERATE or UNSAFE — with a confidence percentage and a plain-language explanation of which parameters drove it.',
    detail: 'MODERATE means the reading sits between clean and unsafe; treat it as a prompt to retest, not as a pass.',
  },
  {
    step: 5,
    title: 'Review it in History',
    icon: 'history',
    body: 'Every submission is stored with its parameters and verdict. Open any row to see the full detail, which is what makes a change over time visible rather than a string of isolated answers.',
    detail: 'Use History to spot a parameter that drifts, which a single reading cannot show.',
  },
  {
    step: 6,
    title: 'Act on unsafe results',
    icon: 'alerts',
    body: 'An UNSAFE verdict raises an alert on the Alerts page and on the dashboard. Do not drink the water until a retest or a laboratory analysis says otherwise.',
    detail: 'This tool flags and explains; it does not replace laboratory testing.',
  },
]

/**
 * Why an unsafe verdict matters — what actually goes wrong if the water is used.
 *
 * Grouped by consequence rather than by parameter, because a user deciding what
 * to do next cares about "will this make me ill", not about which reading broke
 * the threshold.
 */
export const UNSAFE_CONSEQUENCES = [
  {
    tone: 'unsafe',
    title: 'Waterborne illness',
    body: 'Pathogens survive in cloudy, under-disinfected water. Cholera, typhoid, giardia and hepatitis A are the classic outcomes, and they hit children and the elderly hardest.',
  },
  {
    tone: 'unsafe',
    title: 'Heavy metals over time',
    body: 'Lead, arsenic and mercury dissolve into water from pipes and ground. They do not cause a sudden illness; they accumulate, and the damage to kidneys and the nervous system shows up years later.',
  },
  {
    tone: 'moderate',
    title: 'Long-term organ strain',
    body: 'High TDS and nitrate load the kidneys and thyroid. The reading is not a poisoning event, which is exactly why it is easy to ignore and why it is worth flagging.',
  },
  {
    tone: 'moderate',
    title: 'Damage to the system itself',
    body: 'Corrosive or scaling water eats through pipes, tanks and appliances. The water may look fine while it is quietly dissolving the plumbing it sits in.',
  },
]

/**
 * STEP 31 — HOW LOCATION PREDICTION WORKS, CARD BY CARD.
 *
 * The step rail above describes the MANUAL prediction flow: five numbers typed by
 * hand. This list describes the other one, and it is a genuinely different flow —
 * nothing is typed, the place is found instead, and the readings arrive from the
 * server rather than from a test strip. A user who has only read `GUIDE_STEPS`
 * would not know that Location Prediction exists at all, which is why it gets its
 * own section on the same page.
 *
 * Six steps, because those are the six things the screen actually asks the user to
 * do, in the order it asks them. Split any further and a card stops being one
 * action; merge any two and a card starts describing two actions.
 *
 * Each entry carries, beyond the copy the card renders:
 *
 *   - `icon`, so the card's badge matches the step it is describing and reuses the
 *     same icon vocabulary as the rest of the application
 *   - `points`, the short list under the body. The body says what happens; the
 *     points say what specifically, which is where the searchable nouns (city,
 *     pincode, college, shop…) live so they are legible at a glance rather than
 *     buried in a sentence
 *   - `detail`, one closing line in the accent tone — the thing worth remembering
 *     about the step, phrased as an instruction
 *
 * `points` is an array because the counts genuinely differ (step 1 has a long list,
 * step 3 has none), so the card renders it only when it has something to render.
 * Keeping the empty case in the data rather than special-casing it in the card
 * means adding a point later cannot silently break the layout.
 */
export const LOCATION_GUIDE_STEPS = [
  {
    step: 1,
    title: 'Search a Location',
    icon: 'search',
    body: 'Open Location Prediction and type what you want to check. The search accepts anything you would say out loud about a place — not only formal addresses.',
    points: [
      'City, town, village or area',
      'Pincode',
      'Company, college or school',
      'Shop, landmark or building',
    ],
    detail: 'A single character is enough — suggestions appear as you type.',
  },
  {
    step: 2,
    title: 'Select the Location',
    icon: 'location',
    body: 'Choose the right suggestion from the autocomplete list. Places that repeat their name — a chain, a college with several campuses — list every branch separately.',
    points: [
      'Each result shows area, city, district, state and pincode',
      'Pick the exact point, not just the town',
      'For a repeated place, choose your branch',
    ],
    detail: 'If two places look identical, the one with your district is the one you meant.',
  },
  {
    step: 3,
    title: 'Check Water Source',
    icon: 'droplet',
    body: 'The water source at the chosen point is identified from mapped water data, along with the nearest sources and how far away each one is.',
    points: [
      'Water source type at this location',
      'Nearby sources and their distances',
      'The risks that source carries',
    ],
    detail: 'Where no source is mapped at the exact point, the nearest real sources are listed instead.',
  },
  {
    step: 4,
    title: 'View Water Parameters',
    icon: 'analytics',
    body: 'The five readings the model needs are shown for this location, as a starting point rather than as a lab report.',
    points: ['pH', 'Turbidity (NTU)', 'Total Dissolved Solids (mg/L)', 'Temperature (°C)', 'Dissolved Oxygen (mg/L)'],
    detail: 'Edit any value before you continue — these are defaults, not measurements.',
  },
  {
    step: 5,
    title: 'Analyze Water Quality',
    icon: 'shield',
    body: 'Continue into the prediction. The model takes these five values together and returns a verdict with the reasoning behind it and a confidence figure.',
    points: [
      'All five parameters at once',
      'The reason each one mattered',
      'How much the missing data cost',
    ],
    detail: 'A low confidence means little was known about the water, not that the water is uncertain.',
  },
  {
    step: 6,
    title: 'View Result',
    icon: 'check',
    body: 'The result is one of three verdicts. Each is saved with its location and water source, so a later reading can be compared against this one.',
    points: [
      'SAFE — every parameter in its healthy band',
      'MODERATE — something sits between clean and unsafe',
      'UNSAFE — treat the water as contaminated',
    ],
    detail: 'This tool flags and explains. It does not replace laboratory testing.',
  },
]

/** One-line summary shown above the guide. */
export const GUIDE_INTRO =
  'AquaGuard AI reads five water parameters and returns a SAFE, MODERATE or UNSAFE verdict with the reasoning behind it. Here is the whole workflow, start to finish.'
