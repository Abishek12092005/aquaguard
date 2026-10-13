// STEP 32: rain belongs to Rainy Alerts, not to Location Prediction.
//
// Two things are checked, and both can only be checked in a real browser:
//
//   1. THE LOCATION PAGE SAYS NOTHING ABOUT RAIN. Not the word, not a forecast,
//      not a rain-derived factor. This is read off the RENDERED TEXT rather than
//      off the source, because a check that greps the file would pass while the
//      page still showed a rain factor arriving from the API.
//
//   2. RAINY ALERTS IS STILL A WORKING SCREEN. Step 32 moves rain, it does not
//      delete it, so the other page is checked for its own weather content too —
//      which is the half of this step that a "removed everything" implementation
//      would silently fail.
//
// The water API response is stubbed so the Location page has a place, a water
// source and a risk level to render, INCLUDING a `weather` factor and a raised
// rain status. That is the whole point: the page must still hide the rain even
// when the server volunteers it, which is the only situation in which this step
// can actually be wrong.
export default async function run(page) {
  const out = {}

  const PLACE = {
    name: 'Karaikudi',
    area: null,
    city: 'Karaikudi',
    district: 'Karaikkudi',
    state: 'Tamil Nadu',
    country: 'India',
    pincode: '630001',
    lat: 9.9679,
    lon: 78.7824,
    label: 'Karaikudi, Tamil Nadu, India',
  }

  try {
    await page.route('**/locations/search**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: [PLACE] }),
      }),
    )

    // THE WATER CONTEXT, WITH RAIN DELIBERATELY PRESENT.
    //
    // Shaped to the REAL `/locations/context` response — `risk_level`, not
    // `risk`; `water` and `rain` as sibling keys under `data`. A stub with
    // invented keys is worse than no stub: the page reads nothing from it, shows
    // no water at all, and a check for "does the page show rain" then passes
    // because there was never anything on the page to show.
    await page.route('**/locations/context**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            place: PLACE,
            in_scope: true,
            scope_reason: null,
            water: {
              available: true,
              primary: 'Ground Water',
              exact: true,
              types: ['Ground Water'],
              nearby: [{ name: 'Borewell', kind: 'well', distance_km: 0.4 }],
              nearest: { name: 'Borewell', distance_km: 0.4 },
              supported_types: ['Ground Water', 'Surface Water'],
            },
            rain: {
              status: { key: 'occurring', label: 'Rain is occurring' },
              alert: true,
              current_mm: 24.5,
              message: 'Rain is expected in this area.',
            },
            risks: [{ type: 'fluoride', risk: 'High' }],
            // The weather factor is the leak this step is really about.
            risk_level: {
              level: 'high',
              label: 'High',
              message: null,
              factors: [
                { source: 'source type', detail: 'Borewell (identified from mapped water data)' },
                { source: 'weather', detail: 'rain is occurring in this area' },
              ],
            },
            water_source_type: 'Ground Water',
            water_source_known: true,
            nearby_sources: [{ name: 'Borewell', kind: 'well', distance_km: 0.4 }],
            supported_water_types: ['Ground Water', 'Surface Water'],
            default_parameters: { ph: 7.4, turbidity: 3.1, tds: 420, temperature: 27, dissolved_oxygen: 7.2 },
            default_parameters_detail: { source: 'dataset_based', label: 'Dataset-based estimate' },
            parameter_definitions: [
              { name: 'ph', label: 'pH', unit: 'pH' },
              { name: 'turbidity', label: 'Turbidity', unit: 'NTU' },
              { name: 'tds', label: 'Total Dissolved Solids', unit: 'mg/L' },
              { name: 'temperature', label: 'Temperature', unit: '°C' },
              { name: 'dissolved_oxygen', label: 'Dissolved Oxygen', unit: 'mg/L' },
            ],
          },
        }),
      }),
    )

    // --- 1. THE LOCATION PAGE -------------------------------------------
    await page.goto('http://127.0.0.1:5173/location', { waitUntil: 'domcontentloaded' })
    // The real handle on the search box: `aria-label`, not a placeholder match.
    // The placeholder is user-facing copy and is expected to be reworded; the
    // accessible name is what the control IS, and a check written against the
    // former breaks on a copy change that never touched behaviour.
    await page.waitForSelector('input[aria-label="Search a location"]', { timeout: 90000 })

    const box = page.locator('input[aria-label="Search a location"]')
    await box.fill('karaikudi')
    // The suggestions are a `listbox`; its options are its buttons.
    await page.waitForSelector('#location-suggestions', { timeout: 30000 })
    await page.locator('#location-suggestions button').first().click().catch(() => { })
    // Long enough for the water context to resolve and the risk card to render.
    await page.waitForTimeout(6000)

    const text = await page.evaluate(() => document.body.innerText)
    // A guard rather than a check: if the water context never rendered, every
    // assertion below is meaningless, so this is recorded and read first.
    out.pageLoaded = text.length > 200

    // THE PAGE'S OWN TEXT, NOT THE WHOLE DOCUMENT.
    //
    // `document.body.innerText` includes the persistent sidebar, whose nav item is
    // literally called "Rainy Alerts" — so a whole-document match finds "Rain"
    // three times on a page that is completely clean, and reports a leak that is
    // not there. The main region is the page; the sidebar belongs to every screen.
    const main = await page.evaluate(() => {
      const el = document.querySelector('main') || document.querySelector('[role="main"]')
      return el ? el.innerText : ''
    })
    out.mainFound = main.length > 0

    // WHAT THE PAGE SAYS ABOUT RAIN. "drain"/"training" would match /rain/, so the
    // patterns use word boundaries: this is the word rain as a noun, and the name
    // of the other screen.
    const rainMatches = main.match(/\brain\b|\brainy\b|\brainfall\b|\brainfalling\b|\brain(s|ed|ing)?\b|\bweather\b|\bforecast\b/gi) || []
    out.rainWordsOnPage = rainMatches
    out.noRain = rainMatches.length === 0
    // The pointer to where rain DOES live is NOT asserted here on purpose. The
    // header description was going to carry it, but a page that names its own
    // missing feature is doing the same job as the feature: this screen must
    // read as Location → Water Source → Water Quality → Prediction, full stop.
    // Navigation to Rainy Alerts is the user's job to do.
    out.pointsElsewhere = null

    // The screen still does its actual job — which is what proves the filter is
    // not simply a blank page.
    out.stillHasWater = /Water Source/i.test(main)
    out.stillHasPrediction = /Enter Water Prediction|Analy[sz]e/i.test(main)
    out.stillHasRisk = /Water Quality Risk/i.test(main)
    // And the WATER factor survived the filter, while the weather one did not.
    out.waterFactorShown = /Borewell/.test(main)
    out.weatherFactorHidden = !/is occurring in this area/.test(main)

    // --- 2. RAINY ALERTS IS STILL THERE AND STILL WEATHER ----------------
    // Its own API is stubbed so this does not depend on the device's real state or
    // on the weather service being reachable.
    await page.route('**/locations/rain-alert**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            located: {
              place: 'Karaikudi',
              district: 'Karaikkudi',
              state: 'Tamil Nadu',
              country: 'India',
              forecast_at_state_centre: 'Karaikudi, Tamil Nadu',
            },
            source: 'Open-Meteo',
            weather: {
              status: { key: 'occurring', label: 'Rain is occurring' },
              raining_now: true,
              current_mm: 24.5,
              will_rain: true,
              soon_mm: 18.0,
              total_mm: 42.5,
              // `heavy_day`, not `daily` — the notice names the day it applies to,
              // and the forecast list is `days`. Getting these two keys swapped
              // produces a page that renders neither the warning nor the forecast,
              // which looks exactly like "the feature was removed".
              heavy: true,
              heavy_now: false,
              heavy_day: { date: '2026-10-01', mm: 78.2 },
              message: 'Heavy rain is expected in this area.',
              thresholds: { daily_mm: 64.5, hourly_mm: 12.5 },
              days: [
                { date: '2026-10-01', mm: 78.2 },
                { date: '2026-10-02', mm: 4.1 },
                { date: '2026-10-03', mm: 0 },
              ],
            },
          },
        }),
      }),
    )

    const ctx = page.context()
    await ctx.grantPermissions(['geolocation'], { origin: 'http://127.0.0.1:5173' }).catch(() => { })
    await ctx.setGeolocation({ latitude: 9.9679, longitude: 78.7824 }).catch(() => { })

    await page.goto('http://127.0.0.1:5173/rainy-alerts', { waitUntil: 'domcontentloaded' })
    // The screen opens on an explanation and a button, BY DESIGN — it does not
    // prompt on load. So the check has to press it, or it only ever verifies the
    // intro card and reports the weather half of Step 32 as missing.
    const useLocation = page.getByRole('button', { name: /Use my location/i })
    await useLocation.waitFor({ timeout: 30000 })
    await useLocation.click()
    await page.waitForTimeout(6000)

    const rainText = await page.evaluate(() => document.body.innerText)
    out.rainyAlertsExists = rainText.includes('Rainy Alerts')
    out.rainyAlertsHasWeather = (rainText.match(/\brain\b/gi) || []).length
    out.rainyAlertsShowsRain = /Rain is|rainfall|Rain warnings|forecast/i.test(rainText)
    out.rainyAlertsHasHeavyWarning = /Heavy rain/i.test(rainText)
    out.rainyAlertsHasForecast = /Near-term forecast|Daily rainfall/i.test(rainText)

    // --- 3. THE NAV STILL OFFERS BOTH SCREENS ----------------------------
    await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    const nav = await page.evaluate(() => document.body.innerText)
    out.navHasLocation = nav.includes('Location Prediction')
    out.navHasRainyAlerts = nav.includes('Rainy Alerts')
  } catch (e) {
    out.error = String(e).slice(0, 300)
  }
  return out
}
