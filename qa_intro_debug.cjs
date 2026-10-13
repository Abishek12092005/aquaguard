// Identifies what actually matches the intro selectors, so the QA is measuring
// the real component rather than an assumption about it.
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
    const node = document.querySelector('[data-testid=sea-intro]')
    return {
      foundTag: node ? node.tagName : null,
      foundClass: node ? node.className : null,
      // Everything on the page whose class mentions "intro", so the real
      // animation elements can be identified by what they are rather than by a
      // class name I assumed would survive Tailwind's build.
      introish: [...document.querySelectorAll('*')]
        .filter((el) => /intro/i.test(el.className || ''))
        .slice(0, 12)
        .map((el) => ({ tag: el.tagName, cls: el.className })),
      svgs: document.querySelectorAll('[data-testid=sea-intro] svg').length,
      innerStart: node ? node.innerHTML.slice(0, 220) : null,
    }
  })

  console.log(JSON.stringify(info, null, 2))
  await browser.close()
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })