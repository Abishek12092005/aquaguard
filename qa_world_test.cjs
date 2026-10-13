const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const fs = require('fs')
async function main() {
  const b = await chromium.launch()
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 300)))
  p.on('console', (m) => console.log('C:', m.type(), m.text().slice(0, 200)))
  const html = '<!doctype html><html><body><script>document.title="SET";window.__marker=1<\/script></body></html>'
  fs.writeFileSync('test_host.html', html)
  await p.goto('file:///C:/Users/abishek/OneDrive/Desktop/aquagaurd/test_host.html', { waitUntil: 'load' })
  console.log('title:', await p.title())
  console.log('marker:', await p.evaluate(() => window.__marker))
  // World check: evaluate in the same world the scripts ran in?
  await p.evaluate(() => { window.__viaEval = 1 })
  console.log('viaEval seen by page script? (title trick):', await p.evaluate(() => document.title))
  await b.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
