// Step 32 UI test, pass 2: inject JWT, then read the rendered Location page.
const API = 'http://127.0.0.1:5000/api/v1'

export default async function run(page, ui) {
  const out = {}

  // Fresh token via the real login endpoint (tests bcrypt + JWT as a bonus).
  const login = await page.evaluate(async ({ API, email, password }) => {
    const r = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    return r.json()
  }, { API, email: 'step31test@aquaguard.test', password: 'Str0ngPass!2026' })
  out.loginSuccess = login.success === true
  const token = login?.data?.tokens?.access_token

  await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await page.evaluate((t) => {
    localStorage.setItem('aquaguard.access_token', t)
    localStorage.setItem('aquaguard.refresh_token', t)
    localStorage.setItem('aquaguard.user', JSON.stringify({ name: 'Test User31', email: 'step31test@aquaguard.test' }))
  }, token)

  // LOCATION page — search a famous place.
  await page.goto('http://localhost:5173/location', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)
  const snap = await ui.snapshot()
  out.locationSearchBar = /textbox|search/i.test(snap)
  out.useMyLocation = /my location/i.test(snap)
  out.map = /map/i.test(snap)

  const search = snap.match(/@(e\d+) textbox/g)?.[0]?.match(/@(e\d+)/)?.[1]
  if (search) {
    await ui.fill(search, 'Karaikudi')
    await ui.ref(search).press('Enter')
    // The slow Overpass water lookup; wait for the risk card or an error.
    try {
      await page.waitForFunction(
        () => /Water Quality Risk|Rain|not available|unavailable/i.test(document.body.innerText),
        { timeout: 110000 },
      )
    } catch { /* read whatever is on screen */ }
    const body = await page.evaluate(() => document.body.innerText)
    out.placeFound = /Karaikudi/i.test(body)
    out.districtState = /Sivaganga/i.test(body) && /Tamil Nadu/i.test(body)
    out.pincode = /630001|pincode/i.test(body)
    out.waterSource = /pond water|river water|lake water|ground water|surface water|tank water|Water Source/i.test(body)
    out.rainCard = /Rain|Weather/i.test(body)
    out.riskCard = /Water Quality Risk/i.test(body)
    out.estimatedLabel = /Location-level estimated risk/i.test(body)
    out.parameters = /pH|Turbidity|TDS/i.test(body)
    out.nearby = /Nearby/i.test(body)
    out.enterPredictionBtn = /Enter Water Prediction/i.test(body)
  }

  // Navigate to history (TEST 10) — the earlier API test created a prediction.
  await page.goto('http://localhost:5173/history', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)
  const hist = await page.evaluate(() => document.body.innerText)
  out.historyPincode = /Pincode:\s*630001/i.test(hist)
  out.historyLocation = /Karaikudi/i.test(hist)
  out.historyNoCoordinates = !/\b(10\.06|78\.76)\b/.test(hist)

  return out
}
