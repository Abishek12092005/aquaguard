// The overlay paints nothing at the centre of its own box, so something is
// stacking above it. This walks the ancestor chain of both the overlay and the
// element actually on top, to find the layer that wins.
const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await page.goto('http://localhost:4173/', { waitUntil: 'domcontentloaded', timeout: 300000 })
  await page.waitForSelector('[data-testid=sea-intro]', { timeout: 300000, state: 'attached' })

  const chain = await page.evaluate(() => {
    const walk = (el) => {
      const out = []
      while (el && el !== document.documentElement) {
        const cs = getComputedStyle(el)
        out.push({
          tag: el.tagName,
          cls: (el.className || '').slice(0, 70),
          position: cs.position,
          zIndex: cs.zIndex,
          transform: cs.transform === 'none' ? 'none' : 'has-transform',
          opacity: cs.opacity,
        })
        el = el.parentElement
      }
      return out
    }
    const intro = document.querySelector('[data-testid=sea-intro]')
    const top = document.elementFromPoint(640, 400)
    return {
      introAncestors: walk(intro),
      topAncestors: walk(top),
      // The overlay is `fixed`, so an ancestor with a transform, filter,
      // perspective, or backdrop-filter makes it resolve against THAT ancestor
      // instead of the viewport - which is the classic cause of an overlay
      // appearing to be clipped or mis-stacked.
      introOffsetParent: (() => {
        let p = intro.offsetParent
        return p ? `${p.tagName}.${(p.className || '').slice(0, 60)}` : null
      })(),
    }
  })

  console.log(JSON.stringify(chain, null, 2))
  await browser.close()
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })