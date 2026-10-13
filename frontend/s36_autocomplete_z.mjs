// Does the autocomplete dropdown actually PASS BEHIND the navbar when they
// overlap? The z-index numbers (dropdown 20, navbar 30) already say they should,
// but a z-index alone proves nothing: which element paints on top depends on the
// stacking context each one lives in, and a fixed `z-30` still loses to a
// dropdown whose parent creates a higher context.
//
// So this forces the two to genuinely overlap and asks the browser which element
// is really on top at that point. The dropdown is anchored below the search box,
// so scrolling down walks it upward into the navbar.
export default async function run(page) {
  const out = {}

  await page.route('**/api/v1/locations/search**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          { name: 'Karaikudi', area: null, city: 'Karaikudi', district: 'Karaikkudi', state: 'Tamil Nadu', country: 'India', pincode: '630001', lat: 9.9679, lon: 78.7824, kind: 'town', label: 'Karaikudi, Tamil Nadu, India' },
          { name: 'Karaikudi Anna Nagar', area: 'Anna Nagar', city: 'Karaikudi', district: 'Karaikkudi', state: 'Tamil Nadu', country: 'India', pincode: '630002', lat: 9.97, lon: 78.79, kind: 'landmark', label: 'Anna Nagar, Karaikudi' },
        ],
      }),
    }))

  await page.goto('http://127.0.0.1:5173/location', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('input[aria-label="Search a location"]', { timeout: 60000 })

  // A SHORT viewport. On a 900px-tall window this page barely scrolls (133px of
  // travel), which is not enough to walk a dropdown anchored near the top of the
  // document up under a 64px navbar - the first attempt of this check recorded
  // seven samples and never once produced an overlap, then reported "the navbar
  // did not win" over zero overlapping samples. Compressing the window gives the
  // page real scroll travel, so the overlap is actually reached and measured.
  await page.setViewportSize({ width: 1000, height: 380 })
  await page.waitForTimeout(600)

  const box = page.locator('input[aria-label="Search a location"]')
  await box.fill('karaikudi')
  const shown = await page.locator('#location-suggestions button').first()
    .waitFor({ timeout: 20000 }).then(() => true).catch(() => false)
  out.dropdownAppeared = shown
  if (!shown) return out

  // Walk the page down in small steps until the dropdown's box actually crosses
  // the navbar's, then measure AT that position.
  out.samples = []
  for (const y of [0, 40, 80, 120, 160, 200, 240, 280, 320]) {
    await page.evaluate((yy) => window.scrollTo(0, yy), y)
    await page.waitForTimeout(500)
    const s = await page.evaluate(() => {
      const dd = document.querySelector('#location-suggestions')
      const nav = document.querySelector('header')
      if (!dd || !nav) return null
      const d = dd.getBoundingClientRect()
      const n = nav.getBoundingClientRect()
      const overlapTop = Math.max(d.top, n.top)
      const overlapBottom = Math.min(d.bottom, n.bottom)
      if (overlapBottom <= overlapTop) return { y: window.scrollY, overlaps: false }

      // A point inside BOTH boxes. Sampled a little below the navbar's top edge,
      // where the dropdown's own options definitely are.
      const py = Math.round(overlapTop + Math.min((overlapBottom - overlapTop) / 2, 14))
      const px = Math.round(d.left + d.width / 2)
      const top = document.elementFromPoint(px, py)
      const navWins = !!top && (top === nav || nav.contains(top))
      const ddWins = !!top && dd.contains(top)
      return {
        y: window.scrollY, overlaps: true, point: [px, py],
        topIsNavbar: navWins, topIsDropdown: ddWins,
        topTag: top ? (top.tagName + '.' + String(top.className).slice(0, 40)) : null,
        dropdownZ: getComputedStyle(dd).zIndex,
        navbarZ: getComputedStyle(nav).zIndex,
      }
    })
    out.samples.push(s)
  }

  const overlapping = out.samples.filter((s) => s && s.overlaps)
  out.overlapAchieved = overlapping.length > 0
  out.navbarWonEveryOverlap = overlapping.length > 0 &&
    overlapping.every((s) => s.topIsNavbar === true)
  out.measurements = overlapping
  return out
}
