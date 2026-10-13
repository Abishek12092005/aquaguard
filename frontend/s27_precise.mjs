// STEP 27, measured precisely.
//
// The first run left two things ambiguous and both need a real signal rather
// than an inference:
//
//  * `mapMoved` read the map-pane CSS transform, which Leaflet leaves at
//    translate3d(0,0,0) when the change is a re-centre. The map's OWN centre is
//    the honest thing to read.
//  * `panelChangedOnDrag` was false, which is NOT necessarily a bug: a 35px
//    drag at zoom 12 is well under a kilometre, and the reverse-geocode of a
//    point 900 m from the town centre legitimately returns the SAME town. The
//    question is whether the PIN moved, which the coordinate readout answers
//    directly.
export default async function run(page) {
  const out = {}
  try {
    await page.waitForSelector('button[aria-label="Pick a location on the map"]', { timeout: 90000 })
    await page.locator('button[aria-label="Pick a location on the map"]').click()
    await page.waitForSelector('[role="dialog"]', { timeout: 30000 })
    await page.waitForFunction(
      () => document.querySelectorAll('.leaflet-tile-loaded').length > 0,
      { timeout: 90000 },
    )

    // THE MAP'S VIEW, read from the TILE URLs it is actually displaying.
    //
    // The pane's CSS transform stays at translate3d(0,0,0) when Leaflet
    // re-centres, so it is not a signal. The tiles are: a world view at zoom 2
    // and a town at zoom 12 are entirely different tiles, and their z/x/y are
    // Leaflet's own statement of where the map is looking. No production code is
    // added to make this testable.
    const centre = () =>
      page.evaluate(() => {
        const tiles = [...document.querySelectorAll('.leaflet-tile')]
          .map((t) => (t.src || '').match(/\/(\d+)\/(\d+)\/(\d+)\.png/))
          .filter(Boolean)
          .map((m) => `${m[1]}/${m[2]}/${m[3]}`)
        return [...new Set(tiles)].sort().slice(0, 6)
      })

    const centreBefore = await centre()
    out.centreBefore = centreBefore

    // TYPE -> SUGGESTIONS
    const bar = page.locator('[data-testid="map-search"]')
    await bar.fill('Karaikudi')
    await page.waitForSelector('[data-testid="map-suggestion"]', { timeout: 60000 })
    out.suggestionCount = await page.locator('[data-testid="map-suggestion"]').count()

    // SELECT
    await page.locator('[data-testid="map-suggestion"]').first().click()
    await page.waitForTimeout(6000)
    out.centreAfter = await centre()
    out.mapMoved = JSON.stringify(out.centreBefore) !== JSON.stringify(out.centreAfter)
    out.stillOneMap = (await page.locator('.leaflet-container').count()) === 1
    out.pinPlaced = (await page.locator('.aquaguard-map-pin').count()) > 0

    // THE PIN'S COORDINATES, read from the readout the modal shows for a manual
    // pin. This is the value "Use This Location" acts on, so it is the one that
    // has to follow the search - and the one that has to follow a drag.
    const readout = () =>
      page.evaluate(() => {
        const m = document.querySelector('[role="dialog"]')
        const hit = (m.innerText || '').match(/-?\d+\.\d{3,5},\s*-?\d+\.\d{3,5}/)
        return hit ? hit[0] : null
      })
    out.readoutAfterSearch = await readout()

    // DRAG THE PIN, and zoom in first so the drag covers real ground rather
    // than tens of metres - otherwise a correct implementation would legitimately
    // return the same town and prove nothing.
    await page.locator('.leaflet-control-zoom-in').click()
    await page.waitForTimeout(1500)
    await page.locator('.leaflet-control-zoom-in').click()
    await page.waitForTimeout(2500)

    const marker = page.locator('.aquaguard-map-pin').first()
    const mb = await marker.boundingBox()
    if (mb) {
      await page.mouse.move(mb.x + mb.width / 2, mb.y + mb.height / 2)
      await page.mouse.down()
      await page.mouse.move(mb.x + mb.width / 2 + 90, mb.y + mb.height / 2 + 60, { steps: 15 })
      await page.mouse.up()
      await page.waitForTimeout(12000)
    }
    out.readoutAfterDrag = await readout()
    out.pinActuallyMoved =
      Boolean(out.readoutAfterSearch && out.readoutAfterDrag) &&
      out.readoutAfterSearch !== out.readoutAfterDrag
    out.centreAfterDrag = await centre()
    out.mapMovedOnDrag = JSON.stringify(out.centreAfterDrag) !== JSON.stringify(out.centreAfter)

    out.panelAfterDrag = (await page.locator('[data-testid="map-place"]').innerText())
      .replace(/\n+/g, ' | ').slice(0, 220)

    // CONFIRM, and check the page landed where the PIN is - not where the search
    // put it. That is the rule that makes the adjustment meaningful. The wait is
    // generous because confirming runs its own server-side reverse-geocode, and
    // judging it after a fixed few seconds reports a slow lookup as a failure.
    await page.getByRole('button', { name: /^Use This Location$/ }).click()
    try {
      await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 90000 })
    } catch { /* reported by modalClosed */ }
    out.modalClosed = (await page.locator('[role="dialog"]').count()) === 0
    try {
      await page.waitForFunction(() => /Selected location/i.test(document.body.innerText), { timeout: 90000 })
    } catch { /* reported by hasCard */ }
    try {
      await page.waitForFunction(() => /Water Quality Parameters/i.test(document.body.innerText), { timeout: 150000 })
    } catch { /* read below */ }
    await page.waitForTimeout(12000)
    const body = await page.locator('body').innerText()
    out.hasCard = /Selected location/i.test(body)
    out.manualBadge = /Manually selected/i.test(body)
    out.hasParameters = /Water Quality Parameters/i.test(body)
    out.hasWaterSourceCard = /Water Source Type/i.test(body)
    out.hasEnterWaterPrediction = /Enter Water Prediction/i.test(body)
    out.hasAnalyzeWaterQuality = /Analyze Water Quality/i.test(body)
    out.pageSearchBox = await page.locator('input[aria-label="Search a location"]').inputValue()
    out.card = body.replace(/\n+/g, ' | ').match(/Selected location[\s\S]{0, 260}/)?.[0] ?? null
  } catch (e) {
    out.error = String(e).slice(0, 300)
  }
  return out
}
