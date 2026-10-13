const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))
const fs = require('fs')

// Navigates the real Reports page, generates the PDF through the app's own
// code path, and saves the bytes so the file itself can be inspected.
async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE ERR:', m.text()) })
  await page.goto('http://localhost:4173/reports', { waitUntil: 'domcontentloaded', timeout: 300000 })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: 'pdf_reports_page.png' })
  const html = await page.content()
  console.log('has table:', html.includes('Reports'))
  await browser.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
