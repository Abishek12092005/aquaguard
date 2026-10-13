// The overlay is `fixed` with `z-index: 100` and has no transformed ancestor, so
// it should win against a plain `position: relative; z-index: auto` shell. This
// checks the ONE thing that would still defeat it: whether the element that owns
// the painted pixel is the overlay's own subtree, and whether the overlay's
// children are actually painting at all (a zero-sized or clipped child looks
// identical to an overlay that is "there but invisible").
const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await page.goto('http://localhost:4173/', { waitUntil: 'domcontentloaded', timeout: 300000 })
  await page.waitForSelector('[data-testid=sea-intro]', { timeout: 300000, state: 'attached' })

  const info = await page.evaluate(() => {
    const intro = document.querySelector('[data-testid=sea-intro]')
    const kids = [...intro.children].map((el) => {
      const r = el.getBoundingClientRect()
      const cs = getComputedStyle(el)
      return {
        cls: (el.className || '').slice(0, 60),
        rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
        opacity: cs.opacity,
        visibility: cs.visibility,
        bg: cs.backgroundImage !== 'none' ? cs.backgroundImage.slice(0, 50) : cs.backgroundColor,
        svgCount: el.querySelectorAll('svg').length,
      }
    })

    // Which of the overlay's descendants is topmost at a few sample points?
    const probe = (x, y) => {
      const el = document.elementFromPoint(x, y)
      return { at: `${x},${y}`, inIntro: el ? intro.contains(el) : null, tag: el ? el.tagName : null }
    }

    return {
      kids,
      probes: [probe(640, 400), probe(200, 700), probe(1100, 700), probe(640, 100)],
      // The animation-delay inline style on the right wave, which is set by JSX
      // and would be a silent no-op if the attribute were wrong.
      rightWaveDelay: (() => {
        const el = [...document.querySelectorAll('div')].find((d) =>
          (d.className || '').includes('animate-intro-wave-right'),
        )
        return el ? getComputedStyle(el).animationDelay : null
      })(),
    }
  })

  console.log(JSON.stringify(info, null, 2))
  await browser.close()
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })