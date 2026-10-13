export default async function run(page, ui) {
  await page.setViewportSize({ width: 375, height: 800 })

  // Stub the backend search so the suggestion list renders without the server.
  await page.route('**/api/v1/locations/search*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: [
          { label: 'Karaikudi', lat: 10.0765, lon: 78.7747, detail: 'Sivaganga district, Tamil Nadu' },
          { label: 'Karaikudi Market Road', lat: 10.078, lon: 78.776, detail: 'Landmark' },
          { label: 'Karaikudi Railway Station', lat: 10.081, lon: 78.772, detail: 'Transit' },
          { label: 'Karaikudi Bus Stand', lat: 10.075, lon: 78.77, detail: 'Transit' },
        ],
      }),
    }),
  )
  await page.route('**/api/v1/locations/context*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }),
  )
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }),
  )

  await page.goto('http://localhost:5199/location', { waitUntil: 'networkidle' }).catch(() => { })
  await page.waitForTimeout(1500)

  const input = page.getByRole('combobox', { name: 'Search a location' })
  await input.click()
  await input.fill('Karaikudi')
  // the app may fetch on debounce — give it a beat
  await page.waitForSelector('#location-suggestions', { timeout: 8000 }).catch(() => { })

  const open = await page.evaluate(() => {
    const sug = document.getElementById('location-suggestions')
    if (!sug) return { present: false }
    const s = getComputedStyle(sug)
    const sr = sug.getBoundingClientRect()
    const bar = document.querySelector('.app-topbar')
    const bcs = getComputedStyle(bar)
    const br = bar.getBoundingClientRect()
    const elInBar = document.elementFromPoint(br.left + br.width / 2, br.top + br.height / 2)
    return {
      present: true,
      list: { zIndex: s.zIndex, position: s.position, top: Math.round(sr.top), bottom: Math.round(sr.bottom), height: Math.round(sr.height) },
      bar: { zIndex: bcs.zIndex, position: bcs.position, top: Math.round(br.top), bottom: Math.round(br.bottom) },
      centerOfBarIsBar: elInBar === bar || !!elInBar?.closest('.app-topbar'),
      barAboveList: bcs.zIndex > s.zIndex,
    }
  })

  // Now scroll with the dropdown open — the list must slide UNDER the bar.
  await page.mouse.wheel(0, 260)
  await page.waitForTimeout(500)
  const scrolled = await page.evaluate(() => {
    const sug = document.getElementById('location-suggestions')
    const bar = document.querySelector('.app-topbar')
    if (!sug || !bar) return { present: false }
    const br = bar.getBoundingClientRect()
    const sr = sug.getBoundingClientRect()
    const elInBar = document.elementFromPoint(br.left + br.width / 2, br.top + br.height / 2)
    const elAtListTop = sr.top >= 0 ? document.elementFromPoint(sr.left + sr.width / 2, Math.max(sr.top + 2, 0)) : null
    return {
      present: true,
      scrollY: Math.round(window.scrollY),
      barTop: Math.round(br.top),
      listTop: Math.round(sr.top),
      listOverlapsBarArea: sr.top < br.bottom,
      centerOfBarIsBar: elInBar === bar || !!elInBar?.closest('.app-topbar'),
      listTopHitsListItself: elAtListTop ? !!elAtListTop.closest('#location-suggestions') : null,
      listTopHitsBar: elAtListTop ? !!elAtListTop.closest('.app-topbar') : null,
    }
  })

  await page.screenshot({ path: 'qa-location-scrolled.png', clip: { x: 0, y: 0, width: 375, height: 260 } })
  return { open, scrolled }
}
