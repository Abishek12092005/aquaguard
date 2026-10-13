// The overlay is a sibling of <Routes>, correctly layered, fully sized and
// opaque — yet Home content wins at every probe. This prints the overlay's
// position relative to #root and to the shell, to see whether it is actually a
// sibling at all or has ended up nested inside the Home page's own subtree.
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
    const describe = (el) =>
      el ? `${el.tagName}${el.id ? '#' + el.id : ''}.${(el.className || '').slice(0, 50)}` : 'null'

    // Walk UP from the overlay: every ancestor, and whether each creates a
    // containing block for `position: fixed`.
    const ancestors = []
    let el = intro.parentElement
    while (el && el !== document.documentElement) {
      const cs = getComputedStyle(el)
      ancestors.push({
        node: describe(el),
        position: cs.position,
        zIndex: cs.zIndex,
        transform: cs.transform,
        filter: cs.filter,
        backdropFilter: cs.backdropFilter,
        perspective: cs.perspective,
        willChange: cs.willChange,
        contain: cs.contain,
        isolation: cs.isolation,
      })
      el = el.parentElement
    }

    // The overlay's own index within its parent.
    const parent = intro.parentElement
    const indexInParent = [...parent.children].indexOf(intro)

    // Any LATER sibling with a position/z-index could paint over it.
    const laterSiblings = [...parent.children].slice(indexInParent + 1).map((s) => {
      const cs = getComputedStyle(s)
      return { node: describe(s), position: cs.position, zIndex: cs.zIndex, transform: cs.transform }
    })

    return {
      ancestors,
      parent: describe(parent),
      indexInParent,
      parentChildCount: parent.children.length,
      laterSiblings,
      rootChildCount: document.getElementById('root').children.length,
    }
  })

  console.log(JSON.stringify(info, null, 2))
  await browser.close()
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })