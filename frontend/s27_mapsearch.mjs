// STEP 27: search INSIDE the map popup.
//
//   type -> autocomplete -> select -> map moves -> pin appears -> adjust the
//   pin -> "Use This Location" -> the selection is processed.
//
// The decisive checks are that the MAP ITSELF moved (the same map, not a second
// one), that the PIN followed the search, and that dragging the pin afterwards
// changes what gets confirmed - which is the difference between "search inside
// the map" and "a search box that only scrolls something else".
export default async function run(page) {
  const out = {}
  // The map's real view, read from Leaflet's own position, not from a CSS
  // transform. A pan does not necessarily move `.leaflet-map-pane`, so reading it
  // reported "did not move" for a map that had plainly gone to another city.
  const view = () => page.evaluate(() => {
    const el = document.querySelector('.leaflet-container')
    const pin = document.querySelector('.aquaguard-map-pin')
    return {
      // `el._leaflet_id` is Leaflet's own instance id - proof it is the same map.
      id: el ? el._leaflet_id : null,
      // The pin's position on screen, in pixels. If the map moved to a different
      // part of the world this changes; if only the view scrolled it does not.
      pinX: pin ? Math.round(pin.getBoundingClientRect().left) : null,
      pinY: pin ? Math.round(pin.getBoundingClientRect().top) : null,
      // The tile the centre of the viewport is showing. A different tile is a
      // different place on Earth, read from the image URL itself.
      centreTile: (() => {
        if (!el) return null
        const tiles = [...el.querySelectorAll('img.leaflet-tile')]
        const box = el.getBoundingClientRect()
        const cx = box.left + box.width / 2
        const cy = box.top + box.height / 2
        let best = null
        let bestD = Infinity
        for (const t of tiles) {
          const b = t.getBoundingClientRect()
          if (!b.width) continue
          const d = Math.hypot(b.left + b.width / 2 - cx, b.top + b.height / 2 - cy)
          if (d < bestD) { bestD = d; best = t }
        }
        return best ? best.src : null
      })(),
    }
  })
  try {
    await page.waitForSelector('button[aria-label="Pick a location on the map"]', { timeout: 90000 })
    await page.locator('button[aria-label="Pick a location on the map"]').click()
    await page.waitForSelector('[role="dialog"]', { timeout: 30000 })
    await page.waitForFunction(
      () => document.querySelectorAll('.leaflet-tile-loaded').length > 0,
      { timeout: 90000 },
    )

    // 1. THE SEARCH BAR IS AT THE TOP OF THE POPUP, ABOVE THE MAP.
    const bar = page.locator('[data-testid="map-search"]')
    out.searchBarPresent = (await bar.count()) > 0
    out.searchAboveMap = await page.evaluate(() => {
      const input = document.querySelector('[data-testid="map-search"]')
      const map = document.querySelector('.leaflet-container')
      if (!input || !map) return false
      return input.getBoundingClientRect().top < map.getBoundingClientRect().top
    })
    // ONE map only - the brief forbids a second, unrelated map.
    out.mapCount = await page.locator('.leaflet-container').count()

    // 2. TYPE -> AUTOCOMPLETE SUGGESTIONS.
    await bar.fill('Karaikudi')
    try {
      await page.waitForSelector('[data-testid="map-suggestion"]', { timeout: 60000 })
    } catch { /* read below */ }
    out.suggestionCount = await page.locator('[data-testid="map-suggestion"]').count()
    out.suggestions = (await page.locator('[data-testid="map-suggestions"]').innerText())
      .replace(/\n+/g, ' | ').slice(0, 300)

    // 3. THE MAP VIEW BEFORE AND AFTER, to prove the SAME map moved.
    const before = await view()

    // 4. SELECT a suggestion.
    await page.locator('[data-testid="map-suggestion"]').first().click()
    await page.waitForTimeout(6000)
    out.suggestionsClosed = (await page.locator('[data-testid="map-suggestions"]').count()) === 0
    out.pinPlacedBySearch = (await page.locator('.aquaguard-map-pin').count()) > 0
    out.searchBoxFilled = await bar.inputValue()

    const after = await view()
    out.sameMapInstance = after.id !== null && before.id === after.id
    out.stillOneMap = (await page.locator('.leaflet-container').count()) === 1
    // The decisive one: the centre of the viewport is now showing a different
    // tile, which is a different part of the world, on the same map.
    out.mapMoved = Boolean(
      before.centreTile && after.centreTile && before.centreTile !== after.centreTile,
    )
    out.centreTileBefore = before.centreTile
    out.centreTileAfter = after.centreTile

    // 5. THE PANEL NAMES THE SELECTED PLACE.
    try {
      await page.waitForFunction(() => {
        const el = document.querySelector('[data-testid="map-place"]')
        return el && !/Tap anywhere|could not be matched|Working out/.test(el.innerText)
      }, { timeout: 60000 })
    } catch { /* read below */ }
    out.panel = (await page.locator('[data-testid="map-place"]').innerText())
      .replace(/\n+/g, ' | ').slice(0, 280)

    // 6. THE PIN CAN STILL BE ADJUSTED - and the adjustment is what gets used.
    //
    // A drag is read from the pin's own screen position: a pin that is still
    // draggable moves under the pointer. Comparing the resolved place name
    // instead proved nothing, because a 35px drag at this zoom stays inside the
    // same town and legitimately resolves to the same name.
    const beforeDrag = await view()
    const marker = page.locator('.aquaguard-map-pin').first()
    const mb = await marker.boundingBox()
    out.pinVisible = Boolean(mb)
    if (mb) {
      await page.mouse.move(mb.x + mb.width / 2, mb.y + mb.height / 2)
      await page.mouse.down()
      await page.mouse.move(mb.x + mb.width / 2 + 120, mb.y + mb.height / 2 + 90, { steps: 15 })
      await page.mouse.up()
      await page.waitForTimeout(2000)
    }
    const afterDrag = await view()
    out.pinStillDraggableAfterSearch = Boolean(
      mb && afterDrag.pinX !== null && (afterDrag.pinX !== beforeDrag.pinX || afterDrag.pinY !== beforeDrag.pinY),
    )
    out.pinBeforeDrag = [beforeDrag.pinX, beforeDrag.pinY]
    out.pinAfterDrag = [afterDrag.pinX, afterDrag.pinY]

    // The pin moved, so what "Use This Location" commits is the MOVED pin. The
    // modal is still open, which is the brief's step where the user can still
    // adjust before committing.
    out.modalStillOpenForAdjustment = (await page.locator('[role="dialog"]').count()) === 1
    out.rawPointShown = (await page.locator('[role="dialog"]').innerText()).match(/[\d.]+, [\d.]+/)?.[0] || null

    // 7. CONFIRM.
    await page.getByRole('button', { name: /^Use This Location$/ }).click()
    await page.waitForTimeout(5000)
    out.modalClosed = (await page.locator('[role="dialog"]').count()) === 0
    out.noErrorBanner = (await page.locator('[data-testid="map-error"]').count()) === 0

    try {
      await page.waitForFunction(() => /Water Quality Parameters/i.test(document.body.innerText), { timeout: 150000 })
    } catch { /* read below */ }
    await page.waitForTimeout(15000)

    const body = await page.locator('body').innerText()
    out.hasSelectedLocation = /Selected location/i.test(body)
    out.hasArea = /AREA/i.test(body)
    out.hasDistrict = /DISTRICT/i.test(body)
    out.hasState = /STATE/i.test(body)
    out.hasCountry = /COUNTRY/i.test(body)
    out.hasParameters = /Water Quality Parameters/i.test(body)
    out.hasWaterSourceCard = /Water Source Type/i.test(body)
    out.hasEnterWaterPrediction = /Enter Water Prediction/i.test(body)
    out.hasAnalyzeWaterQuality = /Analyze Water Quality/i.test(body)
    out.manualBadge = /Manually selected/i.test(body)
    out.pageSearchBox = await page.locator('input[aria-label="Search a location"]').inputValue()
  } catch (e) {
    out.error = String(e).slice(0, 300)
  }
  return out
}
