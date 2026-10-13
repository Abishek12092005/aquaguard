// STEP 30: the map picker's autocomplete, on Step 30's terms.
//
// Two things are checked, and both are things only the browser can show:
//
//   1. THE MAP PICKER SENDS THE DEVICE AREA. Step 30's tiers 2 and 3 (same
//      state, same district) depend entirely on the client passing that hint.
//      The page's own search box already did; the map picker's did not, so a
//      place found from inside the map ranked differently from the same place
//      found in the box above it. The request is read off the wire, because
//      assuming it from the source would prove nothing about what ships.
//
//   2. SUGGESTIONS APPEAR FOR PARTIAL TEXT, INCLUDING ONE CHARACTER.
//
// The search response is stubbed so the run does not depend on geocoder
// latency, which on this network is long enough to exceed the harness timeout.
// The stub is a realistic tier spread - an exact match, prefixes, and a
// distant place - so the ORDER the user sees is also checked.
export default async function run(page) {
  const out = {}
  out.searchRequests = []
  page.on('request', (r) => {
    if (/\/locations\/search/.test(r.url())) out.searchRequests.push(r.url().split('/api/v1')[1] || r.url())
  })

  const STUB = [
    { name: 'Karaikudi', area: null, city: 'Karaikudi', district: 'Karaikkudi', state: 'Tamil Nadu', country: 'India', pincode: '630001', lat: 9.9679, lon: 78.7824, kind: 'town', label: 'Karaikudi, Tamil Nadu, India' },
    { name: 'Karaikudi Anna Nagar', area: 'Anna Nagar', city: 'Karaikudi', district: 'Karaikkudi', state: 'Tamil Nadu', country: 'India', pincode: '630002', lat: 9.97, lon: 78.79, kind: 'landmark', label: 'Anna Nagar, Karaikudi' },
    { name: 'Karambakkam', area: null, city: 'Karaikudi', district: 'Karaikkudi', state: 'Tamil Nadu', country: 'India', pincode: '630003', lat: 9.98, lon: 78.8, kind: 'town', label: 'Karambakkam, Tamil Nadu' },
    { name: 'Karachi', area: null, city: 'Karachi', district: 'Karachi', state: 'Sindh', country: 'Pakistan', pincode: null, lat: 24.86, lon: 67.01, kind: 'town', label: 'Karachi, Pakistan' },
  ]

  try {
    const ctx = page.context()
    await ctx.grantPermissions(['geolocation'], { origin: 'http://localhost:5173' })
    await ctx.setGeolocation({ latitude: 9.9679, longitude: 78.7824 })
    await page.route('**/locations/search**', async (route) => {
      const url = new URL(route.request().url())
      const q = (url.searchParams.get('q') || '').toLowerCase()
      // The provider's own relevance: a prefix match, then anything else.
      const rows = STUB.filter((r) => r.name.toLowerCase().startsWith(q))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: rows }),
      })
    })
    // The device-area reverse-geocode is stubbed too, so the ranking hint lands
    // without waiting on a real geocoder round trip. The shape is the real one:
    // a state and a district for this device.
    await page.route('**/locations/reverse**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            name: 'Karaikudi', state: 'Tamil Nadu', district: 'Karaikkudi',
            country: 'India', lat: 9.9679, lon: 78.7824,
          },
        }),
      })
    })

    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForSelector('button[aria-label="Pick a location on the map"]', { timeout: 90000 })
    // Wait for the reverse-geocode stub to have been called, which is the signal
    // that the device area has a value the page can send.
    try {
      await page.waitForFunction(
        () => performance.getEntriesByType('resource').some((e) => e.name.includes('/locations/reverse')),
        { timeout: 30000 },
      )
    } catch { /* read below */ }
    await page.waitForTimeout(3000)

    await page.locator('button[aria-label="Pick a location on the map"]').click()
    await page.waitForSelector('[data-testid="map-search"]', { timeout: 30000 })

    const bar = page.locator('[data-testid="map-search"]')
    // ONE CHARACTER - the brief's own example.
    await bar.fill('k')
    try {
      await page.waitForSelector('[data-testid="map-suggestion"]', { timeout: 30000 })
    } catch { /* read below */ }
    out.oneCharCount = await page.locator('[data-testid="map-suggestion"]').count()
    out.oneCharNames = await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid="map-suggestion"]')].map(
        (b) => (b.innerText || '').split('\n')[0].trim(),
      ),
    )
    out.oneCharWorks = out.oneCharCount > 0

    // A full name.
    await bar.fill('karaikudi')
    try {
      await page.waitForFunction(
        () => document.querySelectorAll('[data-testid="map-suggestion"]').length > 0,
        { timeout: 30000 },
      )
    } catch { /* read below */ }
    await page.waitForTimeout(500)
    out.fullNames = await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid="map-suggestion"]')].map(
        (b) => (b.innerText || '').split('\n')[0].trim(),
      ),
    )
    out.fullWorks = out.fullNames.length > 0
    // The EXACT match leads its own result set.
    out.exactLeads = (out.fullNames[0] || '').toLowerCase().startsWith('karaikudi')

    // --- THE DEVICE AREA IS SENT ----------------------------------------
    // A short request means the hint arrived AFTER the box was typed into, which
    // is a real behaviour: the area is resolved asynchronously and a fast
    // typist can outrun it. So the box is cleared and refilled to prove the
    // hint is sent once the area is known, which is what matters.
    await bar.fill('k')
    await page.waitForTimeout(2500)
    out.requests = out.searchRequests.slice(-3)
    const withArea = out.searchRequests.filter((u) => /state=/.test(u) && /district=/.test(u))
    out.sendsDeviceArea = withArea.length > 0
    out.deviceAreaRequests = withArea.slice(0, 2)
    // A request WITHOUT the hint is also fine, as long as the ones after the
    // area resolved carry it. Both are reported rather than only the good one.
    out.requestsWithoutArea = out.searchRequests.filter((u) => !/state=/.test(u)).length
  } catch (e) {
    out.error = String(e).slice(0, 300)
  }
  return out
}
