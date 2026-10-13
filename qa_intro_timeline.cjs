const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await page.goto('http://localhost:4173/', { waitUntil: 'domcontentloaded', timeout: 300000 })
  await page.waitForSelector('[data-testid=sea-intro]', { timeout: 300000, state: 'attached' })

  for (const [t, name] of [[300, 'tl_00'], [1200, 'tl_01'], [2500, 'tl_02'], [4600, 'tl_03']]) {
    await page.waitForTimeout(t === 300 ? 300 : t - [300, 1200, 2500, 4600][[300, 1200, 2500, 4600].indexOf(t) - 1])
    const intro = await page.$('[data-testid=sea-intro]')
    await page.screenshot({ path: `${name}.png` })
    console.log(name, 'introPresent:', !!intro)
  }
  await browser.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
