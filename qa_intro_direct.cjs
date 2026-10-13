// Drives patchright directly so the intro can be sampled with no harness timeout
// in the way. This machine's page loads are slow, and the bundled harness caps
// its own waits at 120s, which is exactly the length of a load here — so the
// animation always finished before anything could look at it.
//
// Nothing in the application is modified: the setTimeout scaling is applied via
// addInitScript (a viewer over the component's own unmount timer) and the CSS is
// slowed through CDP. The source durations are untouched.

const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))

const OUT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'

async function main() {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } })
  const page = await context.newPage()

  // Stretch the component's timers so the 3s intro survives a slow load.
  await page.addInitScript(() => {
    const real = window.setTimeout.bind(window)
    window.setTimeout = (fn, d, ...rest) => real(fn, typeof d === 'number' ? d * 30 : d, ...rest)
  })

  const cdp = await context.newCDPSession(page)
  await cdp.send('Animation.enable')
  await cdp.send('Animation.setPlaybackRate', { playbackRate: 0.5 })

  const t0 = Date.now()
  await page.goto('http://localhost:4173/', { waitUntil: 'domcontentloaded', timeout: 300000 })
  await page.waitForSelector('[data-testid=sea-intro]', { timeout: 300000, state: 'attached' })
  const mountMs = Date.now() - t0

  const scale = () =>
    page.evaluate(() => {
      // Match on the CLASS SUBSTRING, not a literal class selector: Tailwind
      // emits `motion-safe\:animate-intro-wave-left`, and the colon has to be
      // escaped. A substring match is what actually survives the build.
      const read = (needle) => {
        const el = [...document.querySelectorAll('div')].find((d) =>
          (d.className || '').includes(needle),
        )
        if (!el) return null
        const m = new DOMMatrixReadOnly(getComputedStyle(el).transform)
        return Math.round(m.a * 100) / 100
      }
      return {
        left: read('animate-intro-wave-left'),
        right: read('animate-intro-wave-right'),
        overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
        present: !!document.querySelector('[data-testid=sea-intro]'),
      }
    })

  const frames = []
  const grab = async (label) => {
    await page.screenshot({ path: `${OUT}/wave_${label}.png` })
    frames.push({ label, ...(await scale()) })
  }

  await grab('a_far')
  for (const [label, wait] of [['b_approach', 1500], ['c_close', 1500], ['d_filled', 1500]]) {
    await page.waitForTimeout(wait)
    await grab(label)
  }

  console.log(JSON.stringify({ mountMs, frames }, null, 2))
  await browser.close()
}

main().catch((e) => {
  console.error('FAILED:', e.message)
  process.exit(1)
})