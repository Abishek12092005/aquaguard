const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))

// Hides one suspect at a time ~1.6s into the intro (where seams are visible)
// and screenshots, so the seam's source is identified by elimination.
const CASES = ['none', 'shimmer', 'swell', 'right-wave', 'left-wave']

async function main() {
  const browser = await chromium.launch({ headless: true })
  for (const c of CASES) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
    await page.goto('http://localhost:4173/', { waitUntil: 'domcontentloaded', timeout: 300000 })
    await page.waitForSelector('[data-testid=sea-intro]', { timeout: 300000, state: 'attached' })
    await page.evaluate((c) => {
      const intro = document.querySelector('[data-testid=sea-intro]')
      const kids = [...intro.children]
      // layout: 0 bg, 1 light, 2 perspective(waves), 3 swell, 4 shimmer, 5 mark
      const hide = (el) => { if (el) el.style.display = 'none' }
      if (c === 'shimmer') hide(kids[4])
      if (c === 'swell') hide(kids[3])
      if (c === 'right-wave') hide(kids[2].children[1])
      if (c === 'left-wave') hide(kids[2].children[0])
    }, c)
    await page.waitForTimeout(1600)
    await page.screenshot({ path: `probe_${c}.png` })
    await page.close()
  }
  await browser.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
