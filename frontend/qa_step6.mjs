export default async function run(page, ui) {
  // --- 1. Reports page: header must stay fixed while content scrolls
  await page.setViewportSize({ width: 375, height: 800 })
  await page.goto('http://localhost:5199/reports', { waitUntil: 'networkidle' }).catch(() => { })
  await page.waitForTimeout(2000)

  const headerBox = await page.evaluate(() => {
    const h = document.querySelector('.app-topbar')
    if (!h) return null
    const r = h.getBoundingClientRect()
    const cs = getComputedStyle(h)
    return { pos: cs.position, top: r.top, zIndex: cs.zIndex, bg: cs.backgroundColor, height: r.height }
  })

  await page.mouse.wheel(0, 900)
  await page.waitForTimeout(600)
  const afterScroll = await page.evaluate(() => {
    const h = document.querySelector('.app-topbar')
    const r = h.getBoundingClientRect()
    const cs = getComputedStyle(h)
    return { top: r.top, zIndex: cs.zIndex, scrollY: window.scrollY, visible: r.top >= 0 && r.top < 60 }
  })
  await page.screenshot({ path: 'qa-header-scrolled.png', clip: { x: 0, y: 0, width: 375, height: 160 } })

  // --- 2. Location page: open the search suggestions, scroll, hit-test stacking
  await page.goto('http://localhost:5199/location', { waitUntil: 'networkidle' }).catch(() => { })
  await page.waitForTimeout(2000)

  const input = page.getByRole('combobox', { name: 'Search a location' })
  await input.click()
  await input.fill('Karaikudi')
  await page.waitForTimeout(2500) // wait for suggestions

  const sugState = await page.evaluate(() => {
    const sug = document.getElementById('location-suggestions')
    if (!sug) return { present: false }
    const s = getComputedStyle(sug)
    const sr = sug.getBoundingClientRect()
    // which element is on top at the dropdown's top-center point?
    const elAtPoint = document.elementFromPoint(sr.left + sr.width / 2, Math.max(sr.top, 1))
    const chain = []
    let n = elAtPoint
    while (n && n !== document.body) { chain.push(n.id || n.className?.toString().slice(0, 40) || n.tagName); n = n.parentElement }
    return {
      present: true,
      zIndex: s.zIndex,
      position: s.position,
      top: sr.top,
      // elementFromPoint at the bar's area while the list is open — must be the bar, not the list
      coveredByBar: !!elAtPoint?.closest('.app-topbar'),
      hitsHeaderFirst: chain[0]?.includes('app-topbar'),
    }
  })

  // scroll the page with the dropdown open — the list must slide UNDER the bar
  await page.mouse.wheel(0, 300)
  await page.waitForTimeout(500)
  const scrolledState = await page.evaluate(() => {
    const sug = document.getElementById('location-suggestions')
    const bar = document.querySelector('.app-topbar')
    if (!sug || !bar) return { present: false }
    const br = bar.getBoundingClientRect()
    const sr = sug.getBoundingClientRect()
    const elInBar = document.elementFromPoint(br.left + br.width / 2, br.top + br.height / 2)
    return {
      present: true,
      scrollY: window.scrollY,
      barTop: br.top,
      listTop: sr.top,
      listOverlapsBar: sr.top < br.bottom,
      centerOfBarIsBar: elInBar === bar || !!elInBar?.closest('.app-topbar'),
      zBar: getComputedStyle(bar).zIndex,
      zList: getComputedStyle(sug).zIndex,
    }
  })
  await page.screenshot({ path: 'qa-location-scrolled.png', clip: { x: 0, y: 0, width: 375, height: 240 } })

  return { headerBox, afterScroll, sugState, scrolledState }
}
