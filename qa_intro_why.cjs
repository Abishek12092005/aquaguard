// Why does the screenshot show the Home hero rather than the intro overlay,
// when the overlay is present in the DOM and its waves are scaling?
const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

  await page.addInitScript(() => {
    const real = window.setTimeout.bind(window)
    window.setTimeout = (fn, d, ...rest) => real(fn, typeof d === 'number' ? d * 30 : d, ...rest)
  })

  await page.goto('http://localhost:4173/', { waitUntil: 'domcontentloaded', timeout: 300000 })
  await page.waitForSelector('[data-testid=sea-intro]', { timeout: 300000, state: 'attached' })

  const info = await page.evaluate(() => {
    const intro = document.querySelector('[data-testid=sea-intro]')
    const cs = getComputedStyle(intro)
    const r = intro.getBoundingClientRect()

    // What is painted at the CENTRE of the screen, where the overlay sits?
    const atCentre = document.elementFromPoint(640, 400)
    // And near the bottom, where the waves are.
    const atBottom = document.elementFromPoint(640, 700)

    // The first child is the background field; is it actually painting?
    const bg = intro.firstElementChild
    const bgCs = getComputedStyle(bg)
    const bgRect = bg.getBoundingClientRect()

    return {
      reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      darkMode: document.documentElement.classList.contains('dark'),
      introRect: { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top) },
      introStyle: {
        position: cs.position,
        zIndex: cs.zIndex,
        opacity: cs.opacity,
        display: cs.display,
        visibility: cs.visibility,
      },
      bgRect: { w: Math.round(bgRect.width), h: Math.round(bgRect.height) },
      bgClass: bg.className,
      bgBgImage: bgCs.backgroundImage.slice(0, 80),
      elementAtCentre: atCentre ? atCentre.className || atCentre.tagName : null,
      elementAtBottom: atBottom ? atBottom.className || atBottom.tagName : null,
      centreInsideIntro: intro.contains(atCentre),
      bottomInsideIntro: intro.contains(atBottom),
    }
  })

  console.log(JSON.stringify(info, null, 2))
  await browser.close()
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })