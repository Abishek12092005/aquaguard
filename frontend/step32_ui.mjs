// Step 32 UI test: login, then drive the Location flow end to end.
export default async function run(page, ui) {
  const out = {}

  // LOGIN (regression)
  await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const snap = await ui.snapshot()
  out.loginForm = /textbox/i.test(snap)

  const emailRef = snap.match(/@(e\d+) textbox[^\n]*/g)?.[0]?.match(/@(e\d+)/)?.[1]
  const passRef = snap.match(/@(e\d+) textbox[^\n]*/g)?.[1]?.match(/@(e\d+)/)?.[1]
  if (emailRef && passRef) {
    await ui.fill(emailRef, 'step31test@aquaguard.test')
    await ui.fill(passRef, 'Str0ngPass!2026')
    const loginBtn = snap.match(/@(e\d+) button[^\n]*[Ll]og ?in[^\n]*/)?.[1]
      || snap.match(/@(e\d+) button[^\n]*/g)?.find(r => /log ?in|sign ?in/i.test(r))?.match(/@(e\d+)/)?.[1]
    if (loginBtn) {
      await ui.click(loginBtn)
      await page.waitForTimeout(2500)
      out.afterLoginUrl = page.url()
    }
  }

  // LOCATION page
  await page.goto('http://localhost:5173/location', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2000)
  const locSnap = await ui.snapshot()
  out.locationSearchBar = /textbox|search/i.test(locSnap)
  out.useMyLocation = /my location/i.test(locSnap)
  out.mapPin = /map|pin/i.test(locSnap)

  // Search Karaikudi (a famous place / TEST 4+7)
  const search = locSnap.match(/@(e\d+) textbox/g)?.[0]?.match(/@(e\d+)/)?.[1]
  if (search) {
    await ui.fill(search, 'Karaikudi')
    const btn = locSnap.match(/@(e\d+) button/g)
      ?.map(r => r.match(/@(e\d+)/)?.[1])
      ?.find(() => true)
    // submit via Enter
    await ui.ref(search).press('Enter')
    // Karaikudi resolves fast (geocoding only); water context is the slow call
    await page.waitForTimeout(45000)
    const bodyText = await page.evaluate(() => document.body.innerText)
    out.placeFound = /Karaikudi/i.test(bodyText)
    out.waterSource = /Water Source|pond water|river water|lake water|ground water|surface water/i.test(bodyText)
    out.rainCard = /Rain|Weather/i.test(bodyText)
    out.riskCard = /Water Quality Risk/i.test(bodyText)
    out.parametersCard = /Water Quality Parameters|pH|Turbidity/i.test(bodyText)
    out.nearby = /Nearby/i.test(bodyText)
    out.enterPredictionBtn = /Enter Water Prediction/i.test(bodyText)
    out.noVerdictLabelsOnPlaceCards = !/\bUNSAFE\b/.test(bodyText.split('Water Quality Risk')[0])
  }

  return out
}
