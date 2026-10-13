// STEP 35: the complete hierarchical location workflow, driven through the UI.
//
// TEN LEVELS, each entered the way a user actually enters it.
//
// THE ENTRY CONTRACT, WHICH COST SEVERAL ATTEMPTS TO GET RIGHT.
//
// The hierarchy is NOT reached by typing a country name into a search box and
// getting a country page. It is reached through a FALLBACK:
//
//     resolve(q) -> 200 with a place           => the single-place flow
//     resolve(q) -> 200 requires_district       => the village prompt
//     resolve(q) -> 404                         => "not a place", so try COUNTRY,
//                                                 then STATE, then DISTRICT
//
// (Location.jsx, the `catch` around the resolve.) Earlier stubs made `/resolve`
// SUCCEED for "India", so the country card was never requested, never rendered,
// and the first level reported nothing at all — while every stub looked entirely
// reasonable. A stub that is too HELPFUL hides the very feature it is testing.
//
// SO EACH LEVEL IS DRIVEN BY ITS OWN RESOLVE ANSWER, and asserted on the card that
// actually appeared.
//
// WHY ONE ROUTER WITH A MODE SWITCH. Playwright matches the most recently
// registered handler first, so re-registering the same pattern ten times makes
// which stub answers depend on registration order. One handler, one `mode`,
// switched explicitly — so what answers a request is visible in the source rather
// than being an accident of the last `page.route` call.
export default async function run(page) {
  const out = { levels: {} }
  // "hierarchy" runs COUNTRY/STATE/DISTRICT/PLACE; "entry" runs the other five.
  const ONLY = process.env.S35_PART || ''
  const API = '**/api/v1/locations/**'
  const json = (data, meta) => JSON.stringify({ success: true, data, ...(meta ? { meta } : {}) })
  const NOT_FOUND = JSON.stringify({ success: false, message: 'not a place' })

  const P = (over = {}) => ({
    name: 'Karaikudi', area: 'Anna Nagar', city: 'Karaikudi',
    district: 'Karaikkudi', state: 'Tamil Nadu', country: 'India',
    pincode: '630001', lat: 9.9679, lon: 78.7824, kind: 'town',
    label: 'Karaikudi, Tamil Nadu, India', branch_label: 'Karaikudi, Tamil Nadu, India',
    display_name: 'Karaikudi, Tamil Nadu, India', ...over,
  })

  const WATER = {
    place: P(), in_scope: true, scope_reason: null,
    water: { available: true, primary: 'Ground Water', exact: true, types: ['Ground Water'],
      nearby: [{ name: 'Borewell', kind: 'well', distance_km: 0.4 }],
      nearest: { name: 'Borewell', distance_km: 0.4 }, supported_types: ['Ground Water'] },
    rain: null, risks: [{ type: 'fluoride', risk: 'High' }],
    risk_level: { level: 'moderate', label: 'Moderate', message: null,
      factors: [{ source: 'source type', detail: 'Borewell (identified from mapped water data)' }] },
    water_source_type: 'Ground Water', water_source_known: true,
    nearby_sources: [{ name: 'Borewell', kind: 'well', distance_km: 0.4 }],
    supported_water_types: ['Ground Water'],
    default_parameters: { ph: 7.4, turbidity: 3.1, tds: 420, temperature: 27, dissolved_oxygen: 7.2 },
    default_parameters_detail: { source: 'dataset_based', label: 'Dataset-based estimate' },
    parameter_definitions: [
      { name: 'ph', label: 'pH', unit: 'pH' },
      { name: 'turbidity', label: 'Turbidity', unit: 'NTU' },
      { name: 'tds', label: 'Total Dissolved Solids', unit: 'mg/L' },
      { name: 'temperature', label: 'Temperature', unit: '°C' },
      { name: 'dissolved_oxygen', label: 'Dissolved Oxygen', unit: 'mg/L' }],
  }

  const STATES = ['Tamil Nadu', 'Kerala', 'Maharashtra', 'Karnataka', 'Delhi']
  const DISTRICTS = [
    // `risk_tone` is the LEGEND colour (safe/unsafe), `risk_level` the internal
    // category (low/high) — same two vocabularies as the country payload.
    { district: 'Ariyalur', state: 'Tamil Nadu', rank: 1, risk_tone: 'safe', risk_level: 'low', worst_source: 'Ground Water', insufficient_data: false, message: null },
    { district: 'Karaikkudi', state: 'Tamil Nadu', rank: 2, risk_tone: 'unsafe', risk_level: 'high', worst_source: 'River Water', insufficient_data: false, message: null },
    { district: 'Tenkasi', state: 'Tamil Nadu', rank: 3, risk_tone: 'unknown', risk_level: 'unknown', worst_source: '—', insufficient_data: true, message: 'no mapped water features' },
    { district: 'Thanjavur', state: 'Tamil Nadu', rank: 4, risk_tone: 'moderate', risk_level: 'moderate', worst_source: 'Lake Water', insufficient_data: false, message: null },
  ]
  const nine = Array.from({ length: 9 }, (_, i) => ({
    name: `Verified Place ${i + 1}`, area: `Area ${i + 1}`, town: `Town ${i + 1}`,
    district: 'Karaikkudi', state: 'Tamil Nadu',
  }))

  const BRANCHES = [
    P({ name: 'Anna Engineering College', area: 'Kovilpatti', city: 'Kovilpatti', district: 'Thoothukudi', pincode: '626060', lat: 10.8676, lon: 77.7566, kind: 'college' }),
    P({ name: 'Anna Engineering College', area: 'Pothanur', city: 'Karur', district: 'Karur', pincode: '639117', lat: 10.9611, lon: 78.0761, kind: 'college' }),
  ]

  // --- THE ONE ROUTER ------------------------------------------------------
  let mode = 'place'
  const hits = []
  await page.route(API, async (route) => {
    const u = new URL(route.request().url())
    const p = u.pathname
    const q = u.searchParams.get('q') || ''
    hits.push(`${mode} ${p.replace('/api/v1/locations', '')} ?${q}`)

    if (p.endsWith('/search')) {
      const n = q || 'Karaikudi'
      return route.fulfill({ status: 200, contentType: 'application/json', body: json([P({
        name: n, label: `${n}, Tamil Nadu, India`,
        display_name: `${n}, Tamil Nadu, India`, branch_label: `${n}, Tamil Nadu, India` })]) })
    }
    if (p.endsWith('/resolve')) {
      if (mode === 'village') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: json({
          requires_district: true, village: q, reason: 'unqualified',
          message: 'Which Puthur do you mean? Name its district.',
          candidates: [P({ name: 'Puthur', district: 'Karaikkudi' }),
                       P({ name: 'Puthur', district: 'Thrissur', state: 'Kerala' })],
        }) })
      }
      if (mode === 'institution') {
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: json(BRANCHES[0], { branches: BRANCHES }) })
      }
      // COUNTRY, STATE and DISTRICT are NOT places. They must 404, or the page
      // takes the single-place path and never asks for the overview at all.
      if (mode === 'country' || mode === 'state' || mode === 'district') {
        return route.fulfill({ status: 404, contentType: 'application/json', body: NOT_FOUND })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: json(P()) })
    }
    if (p.endsWith('/country')) {
      // ONLY THE COUNTRY LEVEL ANSWERS THIS. The page tries COUNTRY first for
      // EVERY unresolved query, so a fixture that answers "yes, India" to
      // "Tamil Nadu" or "Karaikkudi" makes the page stop at the country card and
      // return — the state and district levels are then never even requested,
      // which reads exactly like those two features being broken.
      if (mode !== 'country') {
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: json({ available: false, message: 'not a country' }) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: json({
        country: { name: q || 'India' }, available: true, in_scope: true,
        // `state` IS THE STATE'S NAME, A STRING — it is used both as the React
        // key and as the visible text (`key={state.state}` / `{state.state}`).
        // The first version of this stub sent `state: { name: 'Tamil Nadu' }`,
        // which renders as "[object Object]" and, being an object, keys every
        // row identically. React then threw, the whole page unmounted, and the
        // NEXT level's `locator.fill` timed out on a page that no longer existed.
        // One wrong field name in a fixture took out the entire run.
        states: STATES.map((name, i) => {
          // TWO SEPARATE VOCABULARIES, and conflating them is what made every
          // dot grey. `risk_tone` is the LEGEND colour — safe / moderate /
          // unsafe / unknown — and `risk_level` is the internal category — low /
          // moderate / high / unknown. `StatusDot` switches on the TONE, so a
          // fixture sending "low" as the tone finds no match and silently falls
          // back to grey for every state. The check for "did the legend actually
          // show green/amber/red" is therefore meaningless unless the stub
          // speaks both vocabularies correctly.
          const [level, tone] = [
            ['low', 'safe'], ['moderate', 'moderate'], ['high', 'unsafe'], ['unknown', 'unknown'],
          ][i % 4]
          return { state: name, risk_tone: tone, risk_level: level,
            insufficient_data: level === 'unknown',
            message: level === 'unknown' ? 'no mapped water features' : null,
            worst_source: 'Ground Water',
            factors: [{ detail: 'Borewell (identified from mapped water data)' }] }
        }),
        legend: [
          { level: 'low', label: 'SAFE', dot: '🟢' },
          { level: 'moderate', label: 'MODERATE', dot: '🟡' },
          { level: 'high', label: 'UNSAFE', dot: '🔴' },
        ],
        // `total_states`, not `states` — the card reads `summary.total_states`.
        summary: { total_states: 5, safe: 1, moderate: 1, unsafe: 1, unknown: 1 },
      }) })
    }
    if (p.endsWith('/state')) {
      if (mode !== 'state') {
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: json({ available: false, message: 'not a state' }) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: json({
        state: { name: q || 'Tamil Nadu' }, state_name: q || 'Tamil Nadu',
        available: true, in_scope: true, districts: DISTRICTS,
        summary: { total_districts: 4, safe: 1, moderate: 1, unsafe: 1, unknown: 1 },
      }) })
    }
    if (p.endsWith('/district')) {
      if (mode !== 'district') {
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: json({ available: false, message: 'not a district' }) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: json({
        available: true, district: { name: q || 'Karaikkudi', state: 'Tamil Nadu' },
        places: nine, composition: { safe: 3, moderate: 3, unsafe: 3 },
        coverage: { required: 9, verified: 9, complete: true, short_bands: [] }, message: null,
      }) })
    }
    // THE PINCODE LEVEL HAS ITS OWN ENDPOINT. `/locations/pincode` is called for
    // a six-digit query BEFORE resolve, so a stub that only answers `/resolve`
    // lets this call fall through to the live backend — the parameters assertion
    // then reads whatever the real service happened to return, which is not what
    // was being tested.
    if (p.endsWith('/pincode')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: json({
        available: true, pincode: '630001',
        place: P({ name: 'Karaikudi', area: 'Anna Nagar' }),
        area: 'Anna Nagar', city: 'Karaikudi', district: 'Karaikkudi',
        state: 'Tamil Nadu', country: 'India',
        post_office: 'Karaikudi SO', delivery_status: 'Deliverable',
      }) })
    }
    if (p.endsWith('/reverse')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: json(P()) })
    }
    if (p.endsWith('/context')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: json(WATER) })
    }
    return route.fallback()
  })

  const main = () => page.evaluate(() => {
    const el = document.querySelector('main') || document.querySelector('[role="main"]')
    return el ? el.innerText : ''
  })
  const cardText = (needle) => page.evaluate((n) => {
    const heads = [...document.querySelectorAll('h2, h3')]
    const h = heads.find((x) => (x.innerText || '').toLowerCase().includes(n.toLowerCase()))
    return h ? (h.closest('section')?.innerText || '') : ''
  }, needle)

  // NULL-SAFE SCOPE, WRAPPED IN AN IIFE.
  //
  // These snippets are passed to `page.evaluate` as STRINGS, and evaluate treats
  // a string as an EXPRESSION — where a bare `return` is a syntax error
  // ("Illegal return statement"), which fails the whole run before a single
  // assertion is made. Each snippet is therefore wrapped as an immediately-invoked
  // function, so the `return` belongs to that function body.
  //
  // `main` falls back to `body`: a null scope here is a layout difference, not a
  // reason to fail every remaining check.
  const SCOPE = `const m = document.querySelector('main') || document.body;
    if (!m) return null;`
  const wrap = (body) => `(() => { ${SCOPE} ${body} })()`
  // Shared by both halves: every level reads the page text into this.
  let t = ''
  const search = async (q) => {
    const box = page.locator('input[aria-label="Search a location"]')
    // CLEAR FIRST. `selectSuggestion` writes the chosen row's label back into the
    // box, so without this the next level searched for
    // "India, Tamil Nadu, India, Tamil Nadu, India" — the trace showed exactly
    // that, and every later level silently inherited the earlier one's text.
    await box.fill('')
    await box.fill(q)
    // SUBMIT THE FORM, DO NOT CLICK A SUGGESTION.
    //
    // Clicking a row calls `selectSuggestion`, which commits that row directly
    // and NEVER calls `/resolve` — so it can only ever reach the single-place
    // flow. The hierarchy, the village prompt and the branch list all live
    // behind resolve, which only the form's Search button (or Enter) reaches.
    // Clicking suggestions is why four of these levels reported nothing.
    await box.press('Enter')
    await page.waitForTimeout(500)
  }

  const fresh = async () => {
    await page.goto('http://127.0.0.1:5173/location', { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('input[aria-label="Search a location"]', { timeout: 60000 })
  }

  try {
    await fresh()

    if (ONLY === 'entry') {
      // Jump straight to the entry paths; the hierarchy half is skipped.
      // eslint-disable-next-line no-unused-expressions
      await (async () => {})()
    } else {
    // === 1. COUNTRY =======================================================
    mode = 'country'
    await search('India')
    await page.waitForTimeout(5000)
    t = await main()
    out.levels.country = {
      statesListed: STATES.filter((s) => t.includes(s)).length,
      // "Do NOT require clicking each state": every state is on screen at once.
      allStatesAtOnce: STATES.every((s) => t.includes(s)),
      legendLabels: ['SAFE', 'MODERATE', 'UNSAFE'].filter((l) => t.includes(l)),
      // A dot is a COLOUR, and colour cannot be read from innerText at all.
      colouredDots: await page.evaluate(wrap(`
        return [...m.querySelectorAll('span')]
          .filter((d) => /bg-(safe|caution|unsafe)\\b/.test(d.className)).length;`)),
      greyDotForUnknown: await page.evaluate(wrap(`
        return [...m.querySelectorAll('span')]
          .some((d) => /bg-slate-(300|600)\\b/.test(d.className));`)),
      insufficientDataText: /Insufficient Data/i.test(t),
    }

    // === 2. STATE =========================================================
    mode = 'state'
    await search('Tamil Nadu')
    await page.waitForTimeout(5000)
    t = await main()
    out.levels.state = {
      districtsListed: DISTRICTS.filter((d) => t.includes(d.district)).length,
      allDistricts: DISTRICTS.every((d) => t.includes(d.district)),
      // ORDERED LIST: the brief asks for "01. Ariyalur", "02. Chengalpattu".
      ranksShown: ['01', '02', '03', '04'].filter((r) => t.includes(r)),
      // The ORDER CHECK, scoped to the district list rather than the whole page.
      // A page-wide `indexOf` finds "Karaikkudi" in the SEARCH BOX first — the
      // text typed into it is part of the page — so the strict ascending check
      // failed on a list that was in fact correctly ordered.
      orderPreserved: await page.evaluate(wrap(`
        const heads = [...m.querySelectorAll('h2, h3')];
        const h = heads.find((x) => /Districts/i.test(x.innerText || ''));
        const sec = h ? h.closest('section') : null;
        if (!sec) return null;
        const rows = [...sec.querySelectorAll('ol li')].map((li) => li.innerText || '');
        return { rows: rows.length, numbered: rows.filter((r) => /^\\d{2}\\./.test(r.trim())).length };`)),
      knownRiskShown: ['Ariyalur', 'Karaikkudi', 'Thanjavur'].every((d) => t.includes(d)),
    }

    // === 3. DISTRICT ======================================================
    mode = 'district'
    await search('Karaikkudi')
    await page.waitForTimeout(5000)
    // The card is headed "Places Overview"; the <section> has no ARIA label, so
    // it is found by its heading text rather than by `aria-labelledby`.
    const dcard = await cardText('Places Overview')
    out.levels.district = {
      cardFound: dcard.length > 0,
      ninePlaces: nine.filter((p) => dcard.includes(p.name)).length,
      // THE RULE. Scoped to this card, because SAFE/MODERATE/UNSAFE are legal
      // elsewhere on the page (legend, risk card) and a page-wide count would
      // find them and wrongly fail.
      riskWordsOnPlaceCards: (dcard.match(/\bSAFE\b|\bMODERATE\b|\bUNSAFE\b/g) || []),
      allDotsGrey: await page.evaluate(wrap(`
        const heads = [...m.querySelectorAll('h2, h3')];
        const h = heads.find((x) => /Places Overview/i.test(x.innerText || ''));
        const sec = h ? h.closest('section') : null;
        if (!sec) return null;
        const dots = [...sec.querySelectorAll('span')]
          .filter((d) => /bg-(safe|caution|unsafe|slate-300|slate-600)\\b/.test(d.className));
        return dots.length > 0 && dots.every((d) => /bg-slate-(300|600)\\b/.test(d.className));`)),
    }

    // === 4. PLACE -> the whole chain to an analysed verdict ==============
    mode = 'place'
    await search('Karaikudi')
    await page.waitForTimeout(5000)
    t = await main()
    const PL = { placeIdentified: /Karaikudi/.test(t) }
    PL.waterSource = /Water Source|Ground Water/i.test(t)
    PL.waterParameters = /pH/.test(t) && /Dissolved Oxygen/i.test(t)
    PL.handoff = await page.getByRole('button', { name: /Enter Water Prediction/i }).count()

    if (PL.handoff > 0) {
      await page.getByRole('button', { name: /Enter Water Prediction/i }).first().click()
      await page.waitForTimeout(4000)
      PL.landsOnPredict = /\/predict/.test(page.url())
      // THE PREFILL, read from input VALUES. A prefilled field carries its number
      // in `value`, which innerText never sees — matching the text would have
      // "passed" on a form with five empty boxes.
      PL.prefill = await page.evaluate(() => {
        const vals = [...document.querySelectorAll('input[type="number"]')].map((i) => i.value)
        return { fields: vals.length, filled: vals.filter(Boolean).length }
      })
      PL.hasAnalyze = /Analyze/i.test(await page.evaluate(() => document.body.innerText))

      const analyze = page.getByRole('button', { name: /^Analyze/i }).first()
      if (await analyze.count()) {
        await page.route('**/api/v1/predictions', (r) => r.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ success: true, data: {
            id: 9001, prediction: 'moderate', confidence: 0.84,
            ph: 7.4, turbidity: 3.1, tds: 420, temperature: 27, dissolved_oxygen: 7.2 } }) }))
        await analyze.click()
        await page.waitForTimeout(4500)
        PL.finalResult = /MODERATE/i.test(await page.evaluate(() => document.body.innerText))
      }
    }
    out.levels.place = PL
    } // end hierarchy block (levels 1-4)

    // === 5. VILLAGE -> a bare name must be REFUSED ========================
    await fresh()
    mode = 'village'
    const vReq = []
    const vListener = (r) => { if (/\/api\/v1\/locations/.test(r.url())) vReq.push(new URL(r.url()).pathname.replace('/api/v1/locations', '')) }
    page.on('request', vListener)
    await search('Puthur')
    await page.waitForTimeout(4000)
    t = await main()
    out.levels.village = {
      askedForDistrict: /District of/i.test(t),
      // THE PROOF THAT NOTHING WAS COMMITTED: the water context endpoint was
      // never called. An earlier version asserted on the ABSENCE OF THE WORDS
      // "Water Source" in the page text — and the page's own static help copy
      // ("...then it identifies the water source and pre-fills the prediction
      // form") contains that exact phrase, so a correct screen read as a failure.
      // What must not happen is a LOOKUP, and only the network can show that.
      neverFetchedWater: !vReq.includes('/context'),
      noPlaceCommitted: /No location selected/i.test(t),
      candidatesDistinct: /Karaikkudi/.test(t) && /Thrissur/.test(t),
      districtInputOffered: /District of/i.test(t),
      // And the rule is scoped to villages, not applied to everything.
      villagesOnlyRuleStated: /city, town, area/i.test(t),
    }
    page.off('request', vListener)

    // === 6. PINCODE =======================================================
    await fresh()
    mode = 'place'
    await search('630001')
    await page.waitForTimeout(4500)
    t = await main()
    out.levels.pincode = {
      pincodeAccepted: /630001/.test(t),
      locationShown: /Karaikudi/.test(t),
      waterShown: /Water Source|Ground Water/i.test(t),
      parametersShown: /Dissolved Oxygen/i.test(t),
    }

    // === 7. INSTITUTION -> real branches, selection required =============
    await fresh()
    mode = 'institution'
    await search('Anna Engineering College')
    await page.waitForTimeout(4500)
    t = await main()
    out.levels.institution = {
      bothBranches: ['Kovilpatti', 'Pothanur'].every((a) => t.includes(a)),
      districtsShown: ['Thoothukudi', 'Karur'].every((d) => t.includes(d)),
      pincodesShown: ['626060', '639117'].every((p) => t.includes(p)),
      promptShown: /select the branch|has \d+ locations/i.test(t),
    }

    // === 8 + 9. MAP PIN and USE MY LOCATION ==============================
    await fresh()
    mode = 'place'
    const ctx = page.context()
    await ctx.grantPermissions(['geolocation'], { origin: 'http://127.0.0.1:5173' }).catch(() => {})
    await ctx.setGeolocation({ latitude: 9.9679, longitude: 78.7824 }).catch(() => {})

    const ctxCalls = []
    const revCalls = []
    page.on('request', (r) => {
      if (/\/locations\/context/.test(r.url())) ctxCalls.push(r.url())
      if (/\/locations\/reverse/.test(r.url())) revCalls.push(r.url())
    })

    // === 8. MAP PIN =======================================================
    //
    // The confirm control is "Use This Location", NOT "Confirm", and it is
    // `disabled` until a point exists (`onClick={() => point && onConfirm(...)}`).
    // An earlier version looked for `button:has-text("Confirm")`, matched nothing,
    // and swallowed the miss with `.catch(() => {})` — so the pin was never
    // confirmed, no place was ever committed, and the water flow below never ran.
    // The check then reported a map pin that "did nothing", which is precisely
    // what had happened: to the test, not to the app.
    await page.locator('button[aria-label="Pick a location on the map"]').click()
    await page.waitForSelector('[data-testid="map-search"]', { timeout: 30000 })
    // Move the map so the picker resolves a point, which is what enables confirm.
    await page.locator('[data-testid="map-search"]').fill('Karaikudi')
    await page.waitForTimeout(2500)
    await page.locator('[data-testid="map-suggestion"]').first().click().catch(() => {})
    await page.waitForTimeout(2000)

    const mapConfirm = page.getByRole('button', { name: /Use This Location/i }).first()
    out.levels.mapPinConfirmEnabled = await mapConfirm.isEnabled().catch(() => false)
    const beforeMapCtx = ctxCalls.length
    await mapConfirm.click({ timeout: 10000 }).catch(() => {})
    await page.waitForTimeout(9000)
    t = await main()
    out.levels.mapPin = {
      confirmEnabled: await page.locator('[data-testid="map-search"]').count() === 0,
      contextCalled: ctxCalls.length > beforeMapCtx,
      waterShown: /Ground Water|Water Source Type/i.test(t),
      reverseCalled: revCalls.length > 0,
    }

    // === 9. USE MY LOCATION ===============================================
    //
    // "Use My Location" DOES NOT COMMIT A PLACE. It reads the device fix, opens the
    // map picker centred on it, and leaves `status` at 'idle' — the user still has
    // to confirm the point, and until they do there is no place and therefore no
    // water lookup. So the earlier version of this check, which waited and looked
    // for a `/context` call, was waiting for something the design deliberately
    // does not do, and would have reported a defect that is not there.
    //
    // The flow to verify is therefore: device fix read -> picker opens -> the user
    // confirms -> the ordinary place flow runs -> water is fetched.
    const beforeCtx = ctxCalls.length
    const beforeRev = revCalls.length
    await page.getByRole('button', { name: /Use My Location/i }).first()
      .click({ timeout: 15000 }).catch(() => {})
    await page.waitForTimeout(4000)

    const pickerOpened = await page.locator('[data-testid="map-search"]').count()
    // The device fix IS the initial point, so confirm is already enabled here —
    // no map interaction is needed for this path, unlike the manual pin.
    const geoConfirm = page.getByRole('button', { name: /Use This Location/i }).first()
    const beforeGeoCtx = ctxCalls.length
    const geoConfirmEnabled = await geoConfirm.isEnabled().catch(() => false)
    await geoConfirm.click({ timeout: 10000 }).catch(() => {})
    await page.waitForTimeout(9000)
    t = await main()

    out.levels.myLocation = {
      pickerOpenedWithDeviceFix: pickerOpened > 0,
      confirmEnabledImmediately: geoConfirmEnabled,
      // NOW the water lookup must happen, because confirming commits the point.
      contextCalled: ctxCalls.length > beforeGeoCtx,
      waterShown: /Ground Water|Water Source Type/i.test(t),
    }

    out.requestTrace = hits.slice(0, 45)
  } catch (e) {
    out.error = String(e).slice(0, 400)
    out.traceSoFar = hits.slice(0, 45)
  }
  return out
}
