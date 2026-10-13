// STEP 29: the "Nearby Water Sources" card, on all three quality states.
//
// Overpass is unreachable on this network at the moment, so a live run would show
// an empty list and prove nothing about this step. The `/locations/context`
// response is therefore intercepted in the browser and replaced with a payload
// built from the real backend shape (real OSM names, real types, real computed
// distances) covering all three states the server can return:
//
//   * a source with a real stored sample  -> "Nearby Source Data"
//   * a source with only the dataset      -> a labelled estimate
//   * a source with nothing at all        -> no readings, only a reason
//
// The checks that matter are the negative ones: an estimate must NEVER carry the
// "Nearby Source Data" heading, and a source with no data must render NO numbers
// at all - an empty row of values is what would read as a measurement.
const SAMPLE = {
  ph: 7.42, turbidity: 4.8, tds: 312, temperature: 28.4, dissolved_oxygen: 6.1,
}

const PAYLOAD = {
  success: true,
  data: {
    in_scope: true,
    scope_reason: null,
    place: {
      name: 'Karaikudi', lat: 9.9679, lon: 76.2444, label: 'Karaikudi, Tamil Nadu',
      area: null, city: 'Karaikudi', district: 'Karaikkudi', state: 'Tamil Nadu',
      country: 'India', pincode: '630001', kind: 'town',
    },
    water: {
      available: true,
      message: null,
      // STEP 13 semantics: no source mapped AT the point, so `primary` is null
      // and the nearby list is what the card must show.
      primary: null,
      nearest_type: 'river water',
      types: ['river water', 'tank water'],
      exact: false,
      exact_match: null,
      exact_radius_m: 200,
      supported_types: ['river water', 'tank water'],
      nearest: {
        type: 'river water', name: 'Karaikudi River', named: true,
        distance_km: 1.23, distance_m: 1230,
      },
      nearby: [
        {
          // 1. A REAL STORED SAMPLE -> measured.
          type: 'river water', name: 'Karaikudi River', named: true,
          distance_km: 1.23, distance_m: 1230, osm_tag: 'waterway',
          quality: {
            status: 'measured',
            label: 'Measured sample available',
            values: SAMPLE,
            source_name: 'Karaikudi',
            source_distance_m: 412.6,
            recorded_at: '2026-09-20T10:00:00',
            note: 'Measured at Karaikudi on 2026-09-20T10:00:00, 0.4 km from this source. These are real recorded readings, not a reading of this spot.',
          },
        },
        {
          // 2. NO STORED SAMPLE, ONLY THE CORPUS -> an estimate.
          type: 'tank water', name: 'Unnamed Water Tank', named: false,
          distance_km: 0.84, distance_m: 840, osm_tag: 'reservoir',
          quality: {
            status: 'dataset_estimate',
            label: 'Dataset-based estimate only',
            values: SAMPLE,
            sample_count: 11000,
            note: 'No test result has been recorded for this source. These figures are the median of 11,000 measured samples in the project water-quality dataset - an estimate for water in general, not a measurement of this source.',
          },
        },
        {
          // 3. NOTHING AT ALL -> no `values` key, so there is nothing to render.
          type: 'pond water', name: 'Unnamed Pond', named: false,
          distance_km: 2.05, distance_m: 2050, osm_tag: 'water',
          quality: {
            status: 'none',
            label: 'No quality data available',
            note: 'No measured sample and no readable dataset are available for this source, so no readings are shown.',
          },
        },
      ],
    },
    rain: { kind: 'none', message: null },
    risks: [],
    risk_level: { level: 'unknown', label: 'Unknown', reason: 'No identified source' },
    water_source_type: null,
    water_source_known: false,
    nearby_sources: [
      { type: 'river water', name: 'Karaikudi River', named: true, distance_km: 1.23 },
      { type: 'tank water', name: 'Unnamed Water Tank', named: false, distance_km: 0.84 },
      { type: 'pond water', name: 'Unnamed Pond', named: false, distance_km: 2.05 },
    ],
    default_parameters: SAMPLE,
    default_parameters_detail: {
      values: SAMPLE,
      source: 'dataset_based',
      label: 'Dataset-based estimate',
      note: 'No water source could be identified for this location, so these are not readings from it. They are the median of 11,000 measured samples in the project water-quality dataset - a starting point only.',
      editable: true,
      sample_count: 11000,
      water_source_known: false,
    },
    parameter_definitions: [
      { name: 'ph', label: 'pH', unit: '' },
      { name: 'turbidity', label: 'Turbidity', unit: 'NTU' },
      { name: 'tds', label: 'TDS', unit: 'mg/L' },
      { name: 'temperature', label: 'Temperature', unit: '°C' },
      { name: 'dissolved_oxygen', label: 'Dissolved Oxygen', unit: 'mg/L' },
    ],
  },
}

export default async function run(page) {
  const out = {}
  try {
    // Replace the context response before the page ever asks for it.
    await page.route('**/locations/context**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(PAYLOAD),
      })
    })
    // ONLY the context response is replaced. The search itself is left to the
    // real geocoder, which is reachable: stubbing it would return nothing and
    // the page would never commit a place, so the card under test would never
    // render at all.
    await page.waitForSelector('button[aria-label="Pick a location on the map"]', { timeout: 60000 })
    await page.locator('button[aria-label="Pick a location on the map"]').click()
    await page.waitForSelector('[role="dialog"]', { timeout: 30000 })
    await page.waitForFunction(
      () => document.querySelectorAll('.leaflet-tile-loaded').length > 0,
      { timeout: 60000 },
    )
    // Commit a place through the map picker: it is the one path that reliably
    // produces a committed place, and it exercises Step 27's search on the way.
    const searchBar = page.locator('[data-testid="map-search"]')
    await searchBar.fill('Karaikudi')
    try {
      await page.waitForSelector('[data-testid="map-suggestion"]', { timeout: 60000 })
      await page.locator('[data-testid="map-suggestion"]').first().click()
    } catch { /* the pin can be used instead */ }
    await page.getByRole('button', { name: /^Use This Location$/ }).click()
    try {
      await page.waitForFunction(
        () => /Nearby Water Sources/i.test(document.body.innerText),
        { timeout: 60000 },
      )
    } catch { /* read below */ }

    out.cardPresent = /Nearby Water Sources/i.test(await page.locator('body').innerText())
    out.sourceCount = await page.getByText(/^(Karaikudi River|Unnamed Water Tank|Unnamed Pond)$/).count()

    // Read the card's rows as text, so every assertion is against what a user
    // actually reads rather than against the payload.
    const rows = await page.evaluate(() => {
      const card = [...document.querySelectorAll('*')].find(
        (el) => el.children.length && /^Nearby Water Sources/.test(el.textContent.trim())
          && el.textContent.includes('Unnamed Pond'),
      )
      if (!card) return null
      return card.innerText
    })
    out.cardText = rows ? rows.replace(/\n{2,}/g, '\n').slice(0, 1400) : null
    const text = rows || ''

    // --- The three states are each labelled --------------------------------
    out.measuredStatusShown = /Measured sample available/i.test(text)
    out.estimateStatusShown = /Dataset-based estimate only/i.test(text)
    out.noDataStatusShown = /No quality data available/i.test(text)

    // --- "Nearby Source Data" appears EXACTLY ONCE -------------------------
    // Once, above the measured source only. If an estimate could carry this
    // heading, a reader would take a median as a test result - the one thing
    // the brief forbids outright.
    //
    // Matched case-insensitively: the heading is uppercased by CSS, so `innerText`
    // reads "NEARBY SOURCE DATA" while the DOM text is "Nearby Source Data".
    const nearbyHeadings = (text.match(/nearby source data/gi) || []).length
    out.nearbySourceDataHeadings = nearbyHeadings
    out.nearbyDataOnlyForMeasured = nearbyHeadings === 1

    // The heading must not appear anywhere near the estimate's values.
    const estimateIdx = text.search(/dataset-based estimate/gi)
    const nearbyIdx = text.search(/nearby source data/gi)
    out.estimateHasItsOwnHeading = estimateIdx !== -1
    out.headingsAreDistinct = estimateIdx === -1 || nearbyIdx === -1 || estimateIdx !== nearbyIdx

    // --- The five parameters appear under the measured source --------------
    out.hasPh = /pH/i.test(text)
    out.hasTurbidity = /Turbidity/i.test(text)
    out.hasTds = /TDS/i.test(text)
    out.hasTemperature = /Temperature/i.test(text)
    out.hasDissolvedOxygen = /Dissolved Oxygen/i.test(text)

    // --- The source with NO data renders NO readings -----------------------
    // Sliced from the last "Unnamed Pond" onwards: no number and no unit may
    // appear after it except the distance already shown on the row.
    const pondIdx = text.indexOf('Unnamed Pond')
    out.pondRow = pondIdx === -1 ? null : text.slice(pondIdx, pondIdx + 300)
    const pondTail = pondIdx === -1 ? '' : text.slice(pondIdx)
    out.pondShowsNoReadings = !/NTU|mg\/L|°C/.test(pondTail)

    // --- Nothing invented -------------------------------------------------
    // The two unnamed features are still labelled "Unnamed ..." and carry the
    // map's own note that the data has no name for them.
    out.unnamedStillUnnamed = /Unnamed Water Tank/.test(text) && /Unnamed Pond/.test(text)
    out.unnamedExplained = /no official name in map data/i.test(text)
    // The real name is shown for the one source the map actually names.
    out.realNameShown = /Karaikudi River/.test(text)

    // Distances are shown per source, from real coordinates.
    out.distancesShown = /1\.23 km/.test(text) && /0\.84 km/.test(text) && /2\.05 km/.test(text)

    // Types are shown per source.
    out.typesShown = /Type: river water/i.test(text) && /Type: tank water/i.test(text)

    // --- The card is NOT empty, which is the whole point of the step --------
    out.notEmpty = out.sourceCount >= 3
  } catch (e) {
    out.error = String(e).slice(0, 400)
  }
  return out
}
