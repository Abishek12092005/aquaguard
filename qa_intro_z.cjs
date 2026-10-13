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
    const cs = getComputedStyle(intro)
    const anim = cs.animationName
    return {
      zIndex: cs.zIndex,
      opacity: cs.opacity,
      animationName: anim,
      // The `intro-out` animation drives opacity 1 -> 0. If it is running, the
      // overlay is fading out and that alone explains the Home page showing.
      animations: intro.getAnimations().map((a) => ({
        name: a.animationName || a.transitionProperty,
        state: a.playState,
        time: Math.round(Number(a.currentTime || 0)),
      })),
    }
  })
  console.log(JSON.stringify(info, null, 2))
  await browser.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })