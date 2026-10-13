// STEP 36 - THE FAILURE MODES, IN THE BROWSER.
//
// The happy paths are covered by s36_final_ui.mjs and the model itself by
// test_step36_integration.py. What this file checks is what the USER SEES when
// something goes wrong, because a wrong answer is only half the risk: an app that
// invents a verdict, or that silently swallows an error and shows a stale one, is
// worse than one that refuses.
//
// The rule under test throughout: on any failure the page must show an ERROR and
// must NOT show a Safe/Moderate/Unsafe verdict. A verdict that appears without a
// successful request behind it is exactly the fabrication the brief forbids.
//
// Providers (location search, water sources, weather) are stubbed only where a
// live call is an outage on this machine rather than a defect; the AI call is
// never stubbed for a failure case - it is made to fail.
export default async function run(page) {
  const out = {}

  const errors = []
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 160)))
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text().slice(0, 160))
  })

  const mainText = () =>
    page.evaluate(() => (document.querySelector('main') || document.body).innerText)
  const analyze = async () => {
    await page.getByRole('button', { name: /Analyze/i }).first().click()
  }

  // ---------------------------------------------------- METHOD 2, five failures
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('http://127.0.0.1:5173/predict', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('input[type="number"]', { timeout: 60000 })
  await page.waitForTimeout(2500)

  const fill = async (values) => {
    const inputs = page.locator('input[type="number"]')
    const n = await inputs.count()
    for (let i = 0; i < Math.min(n, values.length); i += 1) await inputs.nth(i).fill(values[i])
    return n
  }

  // --- 1. INVALID INPUT: pH outside 0-14. The browser must refuse locally and the
  // network must never even be attempted, so a verdict cannot appear.
  // The Manual form posts to `/predictions/predict`, NOT `/predictions` - the
  // latter is the stored-row route and is what the backend test uses. Stubbing
  // the wrong one let a real request through and every failure case below then
  // measured a genuine SAFE answer instead of the failure it was meant to be.
  const PREDICT = '**/api/v1/predictions/predict'

  let calls = 0
  const countPost = (route) => { calls += 1; return route.continue() }
  await page.route(PREDICT, countPost)

  calls = 0
  await fill(['99', '1.2', '280', '18', '8.4'])
  await analyze()
  await page.waitForTimeout(3000)
  let txt = await mainText()
  out.invalidInput = {
    verdictShown: /\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/.test(txt),
    errorShown: /between 0 and 14|invalid|out of range|must be/i.test(txt),
    requestAttempted: calls > 0,
  }
  await page.unroute(PREDICT)

  // --- 2. API FAILURE: 500 from the prediction endpoint.
  await page.route(PREDICT, (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ success: false, message: 'Water quality model is unavailable' }),
    }))
  await fill(['7.1', '1.2', '280', '18', '8.4'])
  await analyze()
  await page.waitForTimeout(4000)
  txt = await mainText()
  out.apiFailure = {
    verdictShown: /\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/.test(txt),
    errorShown: /unavailable|error|failed|try again/i.test(txt),
  }
  await page.unroute(PREDICT)

  // --- 3. MODEL FAILURE: the transport succeeds but the body is a model error,
  // which is the shape that is easiest to mistake for a real answer.
  await page.route(PREDICT, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: false, message: 'Model artifact could not be loaded' }),
    }))
  await fill(['7.1', '1.2', '280', '18', '8.4'])
  await analyze()
  await page.waitForTimeout(4000)
  txt = await mainText()
  out.modelFailure = {
    verdictShown: /\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/.test(txt),
    errorShown: /model|could not be loaded|error|failed/i.test(txt),
  }
  await page.unroute(PREDICT)

  // --- 4. NETWORK DROPPED: no response at all.
  await page.route(PREDICT, (route) => route.abort('connectionrefused'))
  await fill(['7.1', '1.2', '280', '18', '8.4'])
  await analyze()
  await page.waitForTimeout(5000)
  txt = await mainText()
  out.networkDrop = {
    verdictShown: /\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/.test(txt),
    errorShown: /network|connection|error|failed|unavailable|try again/i.test(txt),
  }
  await page.unroute(PREDICT)

  // --- 5. SLOW NETWORK: 4s of latency. Under the brief's ~5s ceiling a slow link
  // still has to produce a REAL answer, and the spinner has to be showing while it
  // waits - otherwise the user cannot tell a slow request from a broken one.
  await page.route(PREDICT, async (route) => {
    await new Promise((r) => setTimeout(r, 4000))
    return route.continue()
  })
  await fill(['7.1', '1.2', '280', '18', '8.4'])
  const t0 = Date.now()
  await analyze()
  await page.waitForTimeout(700)
  const spinnerWhileWaiting = await page.evaluate(() => {
    const m = document.querySelector('main') || document.body
    return /analyz|loading|wait/i.test(m.innerText) ||
      !!m.querySelector('[role="status"],[aria-busy="true"],svg.animate-spin,.animate-spin')
  })
  const gotSlow = await page.waitForFunction(
    () => /\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/.test(
      (document.querySelector('main') || document.body).innerText),
    { timeout: 20000 },
  ).then(() => true).catch(() => false)
  const slowMs = Date.now() - t0
  txt = await mainText()
  out.slowNetwork = {
    resultAppeared: gotSlow,
    spinnerWhileWaiting,
    elapsedMs: slowMs,
    verdict: (txt.match(/\b(SAFE|MODERATE|UNSAFE)\b/) || [])[1] || null,
    // The real model says SAFE for these readings - the same answer, from the
    // same model, only later. A different verdict here would mean the slow path
    // had fabricated something.
    verdictIsTheRealOne: /\bSAFE\b/.test(txt),
  }
  await page.unroute(PREDICT)

  // ------------------------------------------- METHOD 1: the location chain's gaps
  // WATER SOURCE MISSING: the place resolves, but nothing nearby knows about water.
  await page.route('**/api/v1/locations/search**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [{
          name: 'Testabad', area: null, city: 'Testabad', district: 'Testdistrict',
          state: 'Teststate', country: 'India', pincode: '600001',
          lat: 12.9712, lon: 80.2425, kind: 'town', label: 'Testabad, Teststate, India',
        }],
      }),
    }))
  // Only `/locations/water` is faked here. A catch-all under /locations would
  // also swallow the search that is being tested.
  // Only `/locations/context` is faked here. A catch-all under /locations would
  // also swallow the search that is being tested.
  await page.route('**/api/v1/locations/context**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          water: {
            available: false,
            message: 'No mapped water source near this location',
            primary: null, nearest: null, nearby: [], types: [],
          },
          risks: [], risk_level: null,
          default_parameters: null,
          default_parameters_detail: null,
          parameter_definitions: [],
        },
      }),
    }))

  await page.goto('http://127.0.0.1:5173/location', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('input[aria-label="Search a location"]', { timeout: 60000 })
  await page.waitForTimeout(2000)
  await page.locator('input[aria-label="Search a location"]').fill('testabad')
  const suggestion = page.locator('#location-suggestions button').first()
  const gotSuggestion = await suggestion.waitFor({ timeout: 20000 }).then(() => true).catch(() => false)
  let picked = false
  if (gotSuggestion) {
    await suggestion.click()
    await page.waitForTimeout(5000)
    txt = await mainText()
    picked = /Analyze/i.test(txt)
  }
  txt = await mainText()
  out.missingWaterSource = {
    suggestionShown: gotSuggestion,
    reachedParameters: picked,
    // Nothing to predict from, so no verdict - and a message that says why.
    verdictShown: /\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/.test(txt),
    explained: /no water|nearby|source|not found|could not|unable/i.test(txt),
  }
  await page.unroute('**/api/v1/locations/context**')

  // -------------------------------------- LOCATION SEARCH PROVIDER DOWN (500)
  await page.route('**/api/v1/locations/search**', (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ success: false, message: 'Location provider unavailable' }),
    }))
  await page.waitForTimeout(500)
  await page.locator('input[aria-label="Search a location"]').fill('karaikudi')
  await page.waitForTimeout(6000)
  txt = await mainText()
  out.locationProviderDown = {
    pageStillAlive: (await page.evaluate(() => (document.querySelector('main') || document.body).innerText.length)) > 100,
    noFakeSuggestions: (await page.locator('#location-suggestions button').count()) === 0,
    verdictShown: /\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/.test(txt),
  }
  await page.unroute('**/api/v1/locations/search**')

  // ---------------------------------------------- NEARBY SOURCE FALLBACK + MISSING
  // WATER-QUALITY DATA
  //
  // The important distinction: a nearby source carries no quality numbers of its
  // own. The page may still predict - the model's inputs are the default readings
  // - but the RESULT PANEL must say the readings are an estimate from the corpus
  // and not a measurement of that well. Silently presenting dataset medians as
  // this well's water is the fabrication the brief forbids, and this is the one
  // case where the app would otherwise be tempted to do it, because the numbers
  // ARE real - just not from here.
  await page.route('**/api/v1/locations/search**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [{
          name: 'Testabad', area: null, city: 'Testabad', district: 'Testdistrict',
          state: 'Teststate', country: 'India', pincode: '600001',
          lat: 12.9712, lon: 80.2425, kind: 'town', label: 'Testabad, Teststate, India',
        }],
      }),
    }))
  // The page does NOT call `/locations/water` - it calls `/locations/context` and
  // reads `.water`, `.risks`, `.risk_level` and `.default_parameters` out of one
  // response. Stubbing `/locations/water` left the context call going to the real
  // backend, which knows nothing about "Testabad" and correctly returned nothing,
  // so the nearby sources under test never rendered.
  await page.route('**/api/v1/locations/context**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          water: {
            available: true,
            message: null,
            primary: 'well',
            types: ['well', 'reservoir'],
            // NOTE the field names: the page reads `row.type` and `row.distance_km`,
            // not `kind`. A stub that used `kind` renders rows with no type and no
            // distance, which reads as "the nearby list is broken" rather than "the
            // stub was wrong" - so the fixture has to match the real contract.
            nearest: {
              name: 'Testabad Well 4', type: 'well', distance_km: 0.8,
              named: true, quality: { status: 'none', label: 'No quality data available' },
            },
            // Present, but carrying no quality block of their own.
            nearby: [
              {
                name: 'Testabad Well 4', type: 'well', distance_km: 0.8, named: true,
                quality: { status: 'none', label: 'No quality data available' },
              },
              {
                name: 'Testabad Reservoir', type: 'reservoir', distance_km: 2.1,
                named: true, quality: { status: 'none', label: 'No quality data available' },
              },
            ],
          },
          risks: [],
          risk_level: null,
          // Real corpus figures, and DECLARED as an estimate rather than a
          // measurement - which is the whole point of this case.
          default_parameters: {
            ph: 7.1, turbidity: 2.4, tds: 320,
            temperature: 25, dissolved_oxygen: 7.2,
          },
          default_parameters_detail: {
            source: 'dataset_estimate',
            label: 'Estimated',
            note: 'Typical values for well water, not a measurement at this location.',
          },
          parameter_definitions: [],
        },
      }),
    }))

  await page.goto('http://127.0.0.1:5173/location', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('input[aria-label="Search a location"]', { timeout: 60000 })
  await page.waitForTimeout(2000)
  await page.locator('input[aria-label="Search a location"]').fill('testabad')
  const nearSug = page.locator('#location-suggestions button').first()
  const gotNear = await nearSug.waitFor({ timeout: 20000 }).then(() => true).catch(() => false)
  if (gotNear) {
    await nearSug.click()
    await page.waitForTimeout(4000)
  }
  txt = await mainText()

  out.nearbyFallback = {
    suggestionShown: gotNear,
    // The nearby sources really are listed, with their distances.
    listsNearby: /Testabad Well 4/.test(txt) && /Testabad Reservoir/.test(txt),
    showsDistance: /0\.8|2\.1|\bkm\b/i.test(txt),
    // MISSING QUALITY DATA, stated as such - never as a measurement.
    labelsTheAbsence: /no quality data available/i.test(txt),
    // The default readings are real corpus figures, and may be predicted on.
    parametersAvailable: (await page.locator('input[type="number"]').count()) >= 5,
  }

  // And the prediction itself still runs, on those declared-estimate readings.
  const numInputs = page.locator('input[type="number"]')
  const nn = await numInputs.count()
  let analyzed = false
  if (nn >= 5) {
    const defaults = ['7.1', '2.4', '320', '25', '7.2']
    for (let i = 0; i < 5; i += 1) await numInputs.nth(i).fill(defaults[i])
    const t = Date.now()
    await analyze()
    analyzed = await page.waitForFunction(
      () => /\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/.test(
        (document.querySelector('main') || document.body).innerText),
      { timeout: 15000 },
    ).then(() => true).catch(() => false)
    txt = await mainText()
    out.nearbyFallback.predictionElapsedMs = Date.now() - t
  }
  out.nearbyFallback.predicted = analyzed
  out.nearbyFallback.verdict = (txt.match(/\b(SAFE|MODERATE|UNSAFE)\b/) || [])[1] || null
  out.nearbyFallback.provenanceStillVisible = /estimate|dataset|nearby|not this exact/i.test(txt)

  await page.unroute('**/api/v1/locations/context**')
  await page.unroute('**/api/v1/locations/search**')

  // ------------------------------------------------------------------- summary
  out.verdictEverAppearedOnFailure = [
    out.invalidInput, out.apiFailure, out.modelFailure, out.networkDrop,
    out.missingWaterSource, out.locationProviderDown,
  ].some((c) => c && c.verdictShown)

  out.pageErrors = errors
  return out
}
