const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const fs = require('fs')
const path = require('path')
const ROOT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'

// Minimal single-PDF render test with tight logging to find the hang.
const single = fs.readFileSync(path.join(ROOT, 'qa_report.pdf')).toString('base64')

async function main() {
  console.log('launching...')
  const b = await chromium.launch()
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 300)))
  p.on('console', (m) => console.log('C:', m.type(), m.text().slice(0, 200)))
  console.log('goto...')
  await p.goto('file:///C:/Users/abishek/OneDrive/Desktop/aquagaurd/pdf_render_host3.html', { waitUntil: 'load' })
  console.log('loaded')
  await p.addScriptTag({ content: `window.__render(${JSON.stringify(single)}, null).then(() => { document.title = 'RENDER_DONE' }).catch(e => { document.title = 'RENDER_ERR ' + e.message })` })
  console.log('script added')
  for (let i = 0; i < 30; i++) {
    await p.waitForTimeout(2000)
    const t = await p.title()
    console.log('poll', i, t)
    if (t.startsWith('RENDER')) break
  }
  const out = await p.evaluate(() => (document.getElementById('out') || {}).value || '')
  console.log('out len:', out.length)
  if (out) fs.writeFileSync(path.join(ROOT, 'render_out.json'), out)
  await b.close()
  console.log('closed')
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
