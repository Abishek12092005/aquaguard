const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const fs = require('fs')
const path = require('path')
const ROOT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'

async function main() {
  const b = await chromium.launch()
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 300)))
  p.on('console', (m) => console.log('C:', m.type(), m.text().slice(0, 250)))
  await p.goto('file:///C:/Users/abishek/OneDrive/Desktop/aquagaurd/pdf_render_host3.html', { waitUntil: 'load' })
  await p.addScriptTag({ content: 'console.log("type of __render:", typeof window.__render); console.log("pdfjsLib:", typeof window.pdfjsLib); document.title = typeof window.__render' })
  await p.waitForTimeout(2000)
  console.log('title:', await p.title())
  console.log('done (from evaluate world):', await p.evaluate(() => window.__done))
  await b.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
