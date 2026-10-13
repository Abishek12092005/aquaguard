/**
 * Render smoke-checks for the two new pages.
 *
 * The API is stubbed (see `tests/stubs/api.js`), so what this proves is that the
 * components build a tree: no missing exports, no bad props, no crash on the
 * first render. Layout is not covered.
 */
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import Admin, { LockScreen } from '@/pages/Admin'
import Location from '@/pages/Location'
import Predict from '@/pages/Predict'

const results = {}

try {
  const html = renderToStaticMarkup(h(Location))
  results.location = {
    ok: html.length > 0,
    length: html.length,
    title: html.includes('Location'),
    // The page must name the water-quality parameters it feeds, so it reads as
    // part of this application rather than a generic map screen.
    namesParameters:
      html.includes('pH') &&
      html.includes('Turbidity') &&
      html.includes('Total Dissolved Solids') &&
      html.includes('Temperature') &&
      html.includes('Dissolved Oxygen'),
    // The location search control is the entry point of the flow.
    hasSearch: html.includes('placeholder'),
  }
} catch (error) {
  results.location = { ok: false, error: String(error) }
}

// `Admin` itself fetches its session state, and a server render does not run
// effects — so the page can only ever show its checking state here. The LOCK
// SCREEN is rendered directly instead, because it is the one thing that must be
// right before anything else on this page is allowed to appear.
try {
  const html = renderToStaticMarkup(
    h(LockScreen, { email: 'admin@aquaguard.test', onUnlock: () => {}, busy: false, error: null }),
  )
  results.lockScreen = {
    ok: html.length > 0,
    length: html.length,
    locked: html.includes('Console locked'),
    // The credential it wants must be named, or every administrator's first
    // attempt is the wrong password.
    separatePasswordNote: html.includes('separate from your account password'),
    showsWhoIsSignedIn: html.includes('admin@aquaguard.test'),
    hasPasswordField: html.includes('type="password"'),
    labelled: html.includes('Admin console password'),
    // Nothing beyond the lock: no tabs, no data.
    leaksTabs: html.includes('User management') || html.includes('Overall reports'),
  }
} catch (error) {
  results.lockScreen = { ok: false, error: String(error) }
}

try {
  const html = renderToStaticMarkup(h(Admin))
  results.admin = {
    ok: html.length > 0,
    length: html.length,
    // The console theme, distinct from the light application chrome.
    darkSurface: html.includes('bg-slate-950'),
    waterAnimation: html.includes('console-bubble') || html.includes('console-scan'),
    restrictedMarker: html.includes('restricted'),
    // While the session is still being checked, no console content may render.
    leaksTabs: html.includes('User management') || html.includes('Overall reports'),
  }
} catch (error) {
  results.admin = { ok: false, error: String(error) }
}

// The location lookup surface, read through the stub the page calls. The flow
// it feeds is: user location -> validation -> water source -> nearby source ->
// distance -> risk -> rain -> automatic prediction parameters -> the EXISTING
// Random Forest endpoint. The stub returns the shape those steps consume.
try {
  const { locationApi } = await import('@/api')
  const response = await locationApi.context({ name: 'Pune' })
  const context = response.data
  results.locationContext = {
    hasPlace: Boolean(context.place?.name),
    hasWater: Boolean(context.water?.primary),
    hasNearby: Array.isArray(context.water?.nearby),
    hasRain: typeof context.rain?.will_rain === 'boolean',
    hasRainStatus: ['none', 'occurring', 'expected_soon'].includes(context.rain?.status?.key),
    hasRisks: Array.isArray(context.risks),
    // The coarse risk category the page shows, in the three-level form.
    hasRiskLevel: ['low', 'moderate', 'high', 'unknown'].includes(context.risk_level?.level),
    // STEP 7: the readings arrive WITH their provenance, so the Predict form can
    // label them instead of presenting them as measurements.
    hasPrefillProvenance: ['estimated', 'dataset_based', 'user_input_required'].includes(
      context.default_parameters_detail?.source,
    ),
    prefillMatchesDetail:
      JSON.stringify(context.default_parameters) ===
      JSON.stringify(context.default_parameters_detail?.values),
    everyParameterDeclared:
      Object.keys(context.default_parameters).sort().join(',') ===
      'dissolved_oxygen,ph,tds,temperature,turbidity',
  }
} catch (error) {
  results.locationContext = { ok: false, error: String(error) }
}

// STEP 7: the Predict page renders on its own (no navigation state), and names
// the five parameters it collects. Rendering it proves the location block and the
// provenance labels build a tree without the pre-fill state they expect.
try {
  const html = renderToStaticMarkup(h(Predict))
  results.predict = {
    ok: html.length > 0,
    length: html.length,
    title: html.includes('Water Quality Prediction'),
    namesParameters:
      html.includes('pH') &&
      html.includes('Turbidity') &&
      html.includes('Total Dissolved Solids') &&
      html.includes('Temperature') &&
      html.includes('Dissolved Oxygen'),
    // The one action the user takes, and it must be the existing endpoint's form.
    hasAnalyze: html.includes('Analyze Water Quality'),
    // With no pre-fill state, every field must say the user must enter a value.
    labelsUserInput: html.includes('User input required'),
  }
} catch (error) {
  results.predict = { ok: false, error: String(error) }
}

// STEP 8: the prediction result contract. The endpoint returns the verdict, the
// confidence, the labelled parameters and the echoed location; the page turns a
// verdict into a plain risk word. This checks the SHAPE the panel is written
// against, without needing a trained model or a database.
try {
  const { PREDICT_RESULT } = await import('@/api')
  results.predictResult = {
    verdictIsOneOfThree: ['safe', 'moderate', 'unsafe'].includes(PREDICT_RESULT.prediction),
    confidenceIsReal: PREDICT_RESULT.confidence > 0 && PREDICT_RESULT.confidence <= 1,
    everyParameterDeclared:
      Object.keys(PREDICT_RESULT.parameters).sort().join(',') ===
      'dissolved_oxygen,ph,tds,temperature,turbidity',
    hasLocation: Boolean(PREDICT_RESULT.location_name),
    hasWaterSource: Boolean(PREDICT_RESULT.water_source_type),
  }
} catch (error) {
  results.predictResult = { ok: false, error: String(error) }
}

// The exact strings the brief requires on the result panel. A server render
// cannot submit the form, so the page's own source is read and checked: the
// disclaimer sentence and the three risk words must be present, and no
// `100%` accuracy claim may be.
try {
  const { readFileSync } = await import('node:fs')
  const source = readFileSync(new URL('./src/pages/Predict.jsx', import.meta.url), 'utf8')
  results.predictPanelCopy = {
    hasDisclaimer: source.includes(
      'AI-based prediction. This result is not a substitute for certified laboratory water testing.',
    ),
    riskWords: ['Low', 'Medium', 'High'].every((word) => source.includes(`'${word}'`)),
    labelsRisk: source.includes('Risk:'),
    claimsFullAccuracy: /100\s?%/.test(source),
  }
} catch (error) {
  results.predictPanelCopy = { ok: false, error: String(error) }
}

console.log(JSON.stringify(results, null, 2))
